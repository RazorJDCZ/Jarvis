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
