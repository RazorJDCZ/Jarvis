from __future__ import annotations

import json

import httpx
import pytest

from jarvis.actions.models import (
    ActionName,
    ActionSource,
    ActionWorkflowPlan,
    AgentGoalComplete,
    ClarificationNeeded,
)
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings


def patch_httpx(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    requests: list[dict[str, object]] | None = None,
) -> None:
    original_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(json.loads(_request.content))
        content = json.dumps(payload)
        return httpx.Response(200, json={"message": {"content": content}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.planner.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )


def patch_chat_messages(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[dict[str, object]],
    requests: list[dict[str, object]] | None = None,
) -> None:
    original_client = httpx.AsyncClient
    queued = list(messages)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(json.loads(request.content))
        if not queued:
            raise AssertionError("El planificador hizo más solicitudes de las esperadas")
        return httpx.Response(200, json={"message": queued.pop(0)})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.planner.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )


def structured_message(
    action: str,
    arguments: dict[str, object],
    *,
    confidence: float = 0.95,
) -> dict[str, object]:
    return {
        "content": json.dumps(
            {
                "direct_request": True,
                "needs_clarification": False,
                "clarification_question": "",
                "goal_complete": False,
                "completion_message": "",
                "continue_after_execution": False,
                "action": action,
                "arguments": arguments,
                "steps": [],
                "confidence": confidence,
            }
        )
    }


@pytest.mark.asyncio
async def test_native_tool_call_is_preferred_and_remains_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.AsyncClient
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "volume__get",
                                "arguments": {},
                            }
                        }
                    ],
                }
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.planner.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    planner = LocalActionPlanner(Settings(), ("volume.get", "volume.set", "window.list"))

    result = await planner.plan("¿A cuánto está el volumen real?")

    assert result.name is ActionName.VOLUME_GET
    assert result.source is ActionSource.LOCAL_MODEL
    assert "tools" in requests[0]
    assert "format" not in requests[0]


@pytest.mark.asyncio
async def test_local_planner_returns_typed_allowlisted_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "volume.set",
            "arguments": {"level": 30},
            "confidence": 0.94,
        },
    )
    planner = LocalActionPlanner(Settings(), ("volume.set", "window.list"))

    result = await planner.plan("configura el sonido a treinta")

    assert result.name is ActionName.VOLUME_SET
    assert result.arguments == {"level": 30}
    assert result.source is ActionSource.LOCAL_MODEL


@pytest.mark.asyncio
async def test_local_planner_returns_bounded_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "none",
            "arguments": {},
            "steps": [
                {"action": "app.open", "arguments": {"name": "notepad"}},
                {"action": "ui.type", "arguments": {"content": "hola"}},
            ],
            "confidence": 0.96,
        },
    )
    planner = LocalActionPlanner(Settings(), ("app.open", "ui.type"))

    result = await planner.plan("abre notepad y escribe hola")

    assert isinstance(result, ActionWorkflowPlan)
    assert tuple(step.name for step in result.steps) == (
        ActionName.APP_OPEN,
        ActionName.UI_TYPE,
    )
    assert result.steps[0].arguments == {"app": "notepad"}
    assert result.steps[1].arguments == {"text": "hola"}
    assert all(step.source is ActionSource.LOCAL_MODEL for step in result.steps)


@pytest.mark.asyncio
async def test_local_planner_preserves_explicit_browser_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "browser.open",
            "arguments": {
                "website": "https://www.youtube.com",
                "navegador": "chrome",
            },
            "steps": [],
            "confidence": 0.96,
        },
    )
    planner = LocalActionPlanner(Settings(), ("browser.open",))

    result = await planner.plan("abre YouTube usando Chrome")

    assert result.name is ActionName.BROWSER_OPEN
    assert result.arguments == {
        "url": "https://www.youtube.com",
        "browser": "chrome",
    }


@pytest.mark.asyncio
async def test_planner_normalizes_numeric_and_spoken_monitor_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "action": "screen.describe",
            "arguments": {"monitor": 1},
            "steps": [],
            "confidence": 0.96,
        },
    )
    planner = LocalActionPlanner(Settings(), ("screen.describe",))

    result = await planner.plan("observa la primera pantalla")

    assert result.name is ActionName.SCREEN_DESCRIBE
    assert result.arguments == {"monitor": "1"}


@pytest.mark.asyncio
async def test_planner_tolerates_a_small_model_duplicating_one_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "action": "app.open",
            "arguments": {"app": "notepad"},
            "steps": [{"action": "app.open", "arguments": {"app": "notepad"}}],
            "confidence": 0.95,
        },
    )
    planner = LocalActionPlanner(Settings(), ("app.open",))

    result = await planner.plan("quiero tener el bloc de notas abierto")

    assert result.name is ActionName.APP_OPEN
    assert result.arguments == {"app": "notepad"}


@pytest.mark.asyncio
async def test_single_observation_step_continues_an_unfinished_computer_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "goal_complete": False,
            "completion_message": "",
            "continue_after_execution": False,
            "action": "none",
            "arguments": {},
            "steps": [{"action": "window.list", "arguments": {}}],
            "confidence": 0.95,
        },
    )
    planner = LocalActionPlanner(Settings(), ("window.list",))

    result = await planner.plan("necesito que organices las ventanas para concentrarme")

    assert result.name is ActionName.WINDOW_LIST
    assert result.continue_goal is True


@pytest.mark.asyncio
async def test_planner_marks_a_dependent_goal_for_verified_replanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "goal_complete": False,
            "completion_message": "",
            "continue_after_execution": True,
            "action": "browser.read",
            "arguments": {},
            "steps": [],
            "confidence": 0.94,
        },
    )
    planner = LocalActionPlanner(Settings(), ("browser.read",))

    result = await planner.plan("lee los resultados y luego elige el mejor")

    assert result.name is ActionName.BROWSER_READ
    assert result.continue_goal is True


@pytest.mark.asyncio
async def test_dependent_plan_stops_at_first_observation_and_discards_guesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "goal_complete": False,
            "completion_message": "",
            "continue_after_execution": True,
            "action": "none",
            "arguments": {},
            "steps": [
                {"action": "browser.search", "arguments": {"query": "cursos"}},
                {"action": "browser.read", "arguments": {}},
                {"action": "screen.click", "arguments": {"target": None}},
                {"action": "browser.read", "arguments": {}},
            ],
            "confidence": 0.95,
        },
    )
    planner = LocalActionPlanner(
        Settings(),
        ("browser.search", "browser.read", "screen.click"),
    )

    result = await planner.plan("busca, compara y abre el mejor curso")

    assert isinstance(result, ActionWorkflowPlan)
    assert [step.name for step in result.steps] == [
        ActionName.BROWSER_SEARCH,
        ActionName.BROWSER_READ,
    ]
    assert result.continue_goal is True


@pytest.mark.asyncio
async def test_planner_omits_a_null_optional_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "goal_complete": False,
            "completion_message": "",
            "continue_after_execution": False,
            "action": "screen.describe",
            "arguments": {"monitor": None},
            "steps": [],
            "confidence": 0.95,
        },
    )
    planner = LocalActionPlanner(Settings(), ("screen.describe",))

    result = await planner.plan("mira la pantalla")

    assert result.name is ActionName.SCREEN_DESCRIBE
    assert result.arguments == {}


@pytest.mark.asyncio
async def test_planner_can_finish_an_active_goal_from_verified_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "goal_complete": True,
            "completion_message": "El curso seleccionado quedó abierto y verificado.",
            "continue_after_execution": False,
            "action": "none",
            "arguments": {},
            "steps": [],
            "confidence": 0.93,
        },
    )
    planner = LocalActionPlanner(Settings(), ("browser.read",))

    result = await planner.plan("continúa el objetivo con la observación")

    assert isinstance(result, AgentGoalComplete)
    assert result.message == "El curso seleccionado quedó abierto y verificado."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"direct_request": False, "action": "none", "arguments": {}, "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": 0.2},
        {"direct_request": True, "action": "shell.run", "arguments": {}, "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": "bad", "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": True},
        {
            "direct_request": True,
            "action": "volume.set",
            "arguments": {},
            "confidence": float("nan"),
        },
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": 1.1},
    ],
)
async def test_local_planner_rejects_unsafe_or_uncertain_output(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    patch_httpx(monkeypatch, payload)
    planner = LocalActionPlanner(Settings(), ("volume.set",))

    assert await planner.plan("haz algo") is None


@pytest.mark.asyncio
async def test_planner_can_be_disabled_without_network() -> None:
    planner = LocalActionPlanner(
        Settings(action_model_planning=False),
        ("volume.set",),
    )

    assert await planner.plan("configura el volumen") is None


@pytest.mark.asyncio
async def test_planner_returns_a_pointed_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": True,
            "clarification_question": "¿En cuál monitor debo buscarlo?",
            "action": "none",
            "arguments": {},
            "steps": [],
            "confidence": 0.91,
        },
    )
    planner = LocalActionPlanner(Settings(), ("screen.find",))

    result = await planner.plan("encuentra eso")

    assert isinstance(result, ClarificationNeeded)
    assert result.question == "¿En cuál monitor debo buscarlo?"
    assert result.original_request == "encuentra eso"


@pytest.mark.asyncio
async def test_planner_receives_bounded_untrusted_session_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "needs_clarification": False,
            "clarification_question": "",
            "action": "browser.read",
            "arguments": {},
            "steps": [],
            "confidence": 0.93,
        },
        requests,
    )
    planner = LocalActionPlanner(Settings(), ("browser.read",))
    context = tuple(
        {
            "request": f"solicitud {index}",
            "action": "browser.search",
            "outcome": f"resultado {index}",
        }
        for index in range(6)
    )

    result = await planner.plan("ahora lee eso", context)

    assert result.name is ActionName.BROWSER_READ
    content = requests[0]["messages"][1]["content"]
    assert "solicitud 0" not in content
    assert "solicitud 2" in content
    assert "solicitud 5" in content
    assert "<contexto_no_confiable>" in content


@pytest.mark.asyncio
async def test_native_payload_exposes_only_semantically_retrieved_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "volume__get", "arguments": {}}}
                ],
            }
        ],
        requests,
    )
    planner = LocalActionPlanner(
        Settings(agent_tool_limit=8), tuple(LocalActionPlanner._TOOL_GUIDE)
    )

    selected = planner.retriever.select(
        "Dime en cuánto está el sonido del equipo", limit=8
    )
    result = await planner._native_plan(
        "Dime en cuánto está el sonido del equipo", (), selected, "qwen3.5:4b"
    )

    assert result.name is ActionName.VOLUME_GET
    exposed = {
        tool["function"]["name"]
        for tool in requests[0]["tools"]
        if isinstance(tool, dict)
    }
    assert exposed == {
        *(planner._function_name(name) for name in selected),
        "agent__complete",
        "agent__clarify",
    }
    assert len(exposed) == 10
    assert "dev__test" not in exposed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_arguments",
    [
        {"level": "alto"},
        {"level": 101},
        {"level": 30, "shell": "format C:"},
        {},
        {"level": True},
    ],
)
async def test_native_tool_call_rejects_malformed_typed_arguments_and_uses_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
    bad_arguments: dict[str, object],
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "volume__set", "arguments": bad_arguments}}
                ],
            },
            structured_message("volume.set", {"level": 30}),
        ],
        requests,
    )
    planner = LocalActionPlanner(Settings(), ("volume.get", "volume.set"))

    result = await planner.plan("Deja el volumen al treinta por ciento")

    assert result.name is ActionName.VOLUME_SET
    assert result.arguments == {"level": 30}
    assert len(requests) == 2
    assert "tools" in requests[0]
    assert "format" in requests[1]


@pytest.mark.asyncio
async def test_native_tool_call_normalizes_safe_argument_aliases_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "volume__set", "arguments": {"value": 35}}}
                ],
            }
        ],
    )
    planner = LocalActionPlanner(Settings(), ("volume.set",))

    result = await planner.plan("Pon el audio en treinta y cinco")

    assert result.name is ActionName.VOLUME_SET
    assert result.arguments == {"level": 35}


@pytest.mark.asyncio
async def test_native_tool_call_cannot_escape_semantic_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "dev__test", "arguments": {"workspace": "Jarvis"}}}
                ],
            },
            structured_message("volume.get", {}),
        ],
        requests,
    )
    planner = LocalActionPlanner(
        Settings(agent_tool_limit=8), tuple(LocalActionPlanner._TOOL_GUIDE)
    )

    result = await planner.plan("Dime el volumen actual")

    assert result.name is ActionName.VOLUME_GET
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_structured_fallback_cannot_escape_semantic_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_chat_messages(
        monkeypatch,
        [
            {"content": "", "tool_calls": []},
            structured_message("dev.test", {"workspace": "Jarvis"}),
        ],
    )
    planner = LocalActionPlanner(
        Settings(agent_tool_limit=8), tuple(LocalActionPlanner._TOOL_GUIDE)
    )

    result = await planner.plan("Dime el volumen actual")

    assert result is None


@pytest.mark.asyncio
async def test_native_dependent_workflow_stops_after_observation_and_persists_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "browser__search",
                            "arguments": {"query": "cursos de Python"},
                        }
                    },
                    {"function": {"name": "browser__read", "arguments": {}}},
                    {
                        "function": {
                            "name": "browser__open_result",
                            "arguments": {"index": 1},
                        }
                    },
                ],
            }
        ],
    )
    planner = LocalActionPlanner(
        Settings(agent_reasoning_enabled=False),
        ("browser.search", "browser.read", "browser.open_result"),
    )

    selected = planner.retriever.select(
        "Investiga y compara cursos; luego abre el mejor", limit=8
    )
    result = await planner._native_plan(
        "Investiga y compara cursos; luego abre el mejor",
        (),
        selected,
        "qwen3.5:4b",
    )

    assert isinstance(result, ActionWorkflowPlan)
    assert [step.name for step in result.steps] == [
        ActionName.BROWSER_SEARCH,
        ActionName.BROWSER_READ,
    ]
    assert result.continue_goal is True


@pytest.mark.asyncio
async def test_native_search_only_keeps_complex_research_goal_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "browser__search",
                            "arguments": {"query": "cursos de Python"},
                        }
                    }
                ],
            }
        ],
    )
    planner = LocalActionPlanner(
        Settings(agent_reasoning_enabled=False), ("browser.search", "browser.read")
    )

    selected = planner.retriever.select(
        "Investiga cursos de Python y recomiéndame el mejor", limit=8
    )
    result = await planner._native_plan(
        "Investiga cursos de Python y recomiéndame el mejor",
        (),
        selected,
        "qwen3.5:4b",
    )

    assert result.name is ActionName.BROWSER_SEARCH
    assert result.continue_goal is True


@pytest.mark.asyncio
async def test_native_agent_complete_requires_current_verified_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = {
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "agent__complete",
                    "arguments": {"message": "El objetivo quedó verificado."},
                }
            }
        ],
    }
    patch_chat_messages(monkeypatch, [message, message])
    planner = LocalActionPlanner(Settings(), ("window.list",))

    rejected = await planner._native_plan(
        "organiza mis ventanas", (), ("window.list",), "qwen3.5:4b"
    )
    completed = await planner._native_plan(
        "continúa el objetivo",
        ({"request": "objetivo", "action": "verified-observation", "outcome": "ok"},),
        ("window.list",),
        "qwen3.5:4b",
    )

    assert rejected is None
    assert isinstance(completed, AgentGoalComplete)
    assert completed.message == "El objetivo quedó verificado."


@pytest.mark.asyncio
async def test_native_agent_clarification_is_bounded_and_preserves_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "agent__clarify",
                            "arguments": {"question": "¿En cuál monitor debo trabajar?"},
                        }
                    }
                ],
            }
        ],
    )
    planner = LocalActionPlanner(
        Settings(agent_reasoning_enabled=False), ("screen.list", "screen.describe")
    )

    result = await planner.plan("Organiza lo que se ve")

    assert isinstance(result, ClarificationNeeded)
    assert result.question == "¿En cuál monitor debo trabajar?"
    assert result.original_request == "Organiza lo que se ve"


def test_every_native_tool_schema_is_closed_and_has_known_types() -> None:
    allowed_types = {"string", "integer", "boolean", "object"}
    for name in LocalActionPlanner._TOOL_GUIDE:
        schema = LocalActionPlanner._tool_parameters(name)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema.get("required", ())).issubset(schema["properties"])
        assert all(
            definition["type"] in allowed_types
            for definition in schema["properties"].values()
        )


@pytest.mark.asyncio
async def test_ambiguous_native_choice_is_replaced_by_structured_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "game__list", "arguments": {}}}
                ],
            },
            structured_message("game.launch", {"game": "Minecraft"}),
        ],
        requests,
    )
    planner = LocalActionPlanner(Settings(), ("game.launch", "game.list"))

    result = await planner.plan("Inicia Minecraft")

    assert result.name is ActionName.GAME_LAUNCH
    assert result.arguments == {"game": "Minecraft"}
    assert len(requests) == 2
    assert "tools" in requests[0]
    assert "format" in requests[1]


@pytest.mark.asyncio
async def test_semantically_aligned_native_choice_remains_single_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "game__launch",
                            "arguments": {"game": "Minecraft"},
                        }
                    }
                ],
            }
        ],
        requests,
    )
    planner = LocalActionPlanner(Settings(), ("game.launch", "game.list"))

    result = await planner.plan("Quiero jugar Minecraft")

    assert result.name is ActionName.GAME_LAUNCH
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_weak_semantic_admission_is_verified_even_when_native_matches_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "screen__describe", "arguments": {}}}
                ],
            },
            {
                "content": json.dumps(
                    {
                        "direct_request": False,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "goal_complete": False,
                        "completion_message": "",
                        "continue_after_execution": False,
                        "action": "none",
                        "arguments": {},
                        "steps": [],
                        "confidence": 0.95,
                    }
                )
            },
        ],
        requests,
    )
    planner = LocalActionPlanner(Settings(), ("screen.describe", "screen.list"))

    result = await planner.plan("El monitor es una tecnología interesante")

    assert result is None
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_structured_verifier_can_veto_ambiguous_native_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = structured_message("none", {})
    rejected_payload = json.loads(rejected["content"])
    rejected_payload["direct_request"] = False
    rejected["content"] = json.dumps(rejected_payload)
    patch_chat_messages(
        monkeypatch,
        [
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "game__list", "arguments": {}}}
                ],
            },
            rejected,
        ],
    )
    planner = LocalActionPlanner(Settings(), ("game.launch", "game.list"))

    result = await planner.plan("Hablemos sobre jugar Minecraft")

    assert result is None
