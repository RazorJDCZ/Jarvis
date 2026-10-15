from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import Settings
from jarvis.providers.codex_app_server import CodexAppServerClient, CodexAppServerError


class RecordingCodexClient(CodexAppServerClient):
    def __init__(
        self,
        settings: Settings,
        answer: str = "Respuesta segura.",
        *,
        coding_server: bool = False,
    ) -> None:
        super().__init__(settings, coding_server=coding_server)
        self.answer = answer
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None:
        self._models = {
            "gpt-5.6-luna": {
                "model": "gpt-5.6-luna",
                "isDefault": True,
                "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "low"},
                    {"reasoningEffort": "medium"},
                    {"reasoningEffort": "high"},
                ],
            }
        }
        self._default_model = "gpt-5.6-luna"

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        del timeout
        self.requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-test"}}
        if method == "turn/start":
            turn_id = "turn-test"
            item = {"id": "item-test", "type": "agentMessage", "phase": "final_answer"}
            await self._dispatch_notification(
                {"method": "item/started", "params": {"turnId": turn_id, "item": item}}
            )
            await self._dispatch_notification(
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "turnId": turn_id,
                        "itemId": "item-test",
                        "delta": self.answer,
                    },
                }
            )
            await self._dispatch_notification(
                {
                    "method": "item/completed",
                    "params": {"turnId": turn_id, "item": {**item, "text": self.answer}},
                }
            )
            await self._dispatch_notification(
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "threadId": "thread-test",
                        "turnId": turn_id,
                        "tokenUsage": {
                            "last": {
                                "totalTokens": 2_130,
                                "inputTokens": 2_100,
                                "cachedInputTokens": 1_500,
                                "cacheWriteInputTokens": 0,
                                "outputTokens": 30,
                                "reasoningOutputTokens": 5,
                            },
                            "modelContextWindow": 258_400,
                        },
                    },
                }
            )
            await self._dispatch_notification(
                {
                    "method": "turn/completed",
                    "params": {"turn": {"id": turn_id, "status": "completed", "items": []}},
                }
            )
            return {"turn": {"id": turn_id}}
        raise AssertionError(f"RPC inesperado: {method}")


@pytest.mark.asyncio
async def test_codex_turn_is_ephemeral_read_only_and_tool_free() -> None:
    chunks: list[str] = []

    async def callback(value: str) -> None:
        chunks.append(value)

    client = RecordingCodexClient(Settings(brain_mode="codex"))
    answer = await client.generate_text(
        developer_instructions="Decide con cuidado.",
        user_input="Hola",
        model="gpt-5.6-luna",
        effort="high",
        callback=callback,
    )

    thread = client.requests[0][1]
    turn = client.requests[1][1]
    assert answer == "Respuesta segura."
    assert chunks == ["Respuesta segura."]
    assert thread["ephemeral"] is True
    assert thread["approvalPolicy"] == "never"
    assert thread["sandbox"] == "read-only"
    assert "No uses herramientas" in thread["baseInstructions"]
    assert turn["approvalPolicy"] == "never"
    assert turn["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    assert "tools" not in thread
    assert "tools" not in turn
    assert client.last_token_usage == {
        "model": "gpt-5.6-luna",
        "effort": "high",
        "total_tokens": 2_130,
        "input_tokens": 2_100,
        "cached_input_tokens": 1_500,
        "cache_write_input_tokens": 0,
        "output_tokens": 30,
        "reasoning_output_tokens": 5,
        "model_context_window": 258_400,
        "uncached_input_tokens": 600,
    }


@pytest.mark.asyncio
async def test_codex_structured_output_is_parsed_and_schema_is_forwarded() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    client = RecordingCodexClient(Settings(brain_mode="codex"), answer='{"ok":true}')

    result = await client.generate_json(
        developer_instructions="Responde JSON.",
        user_input="Comprueba",
        model="gpt-5.6-luna",
        effort="medium",
        output_schema=schema,
    )

    assert result == {"ok": True}
    assert client.requests[1][1]["outputSchema"] == schema


@pytest.mark.asyncio
async def test_codex_forwards_validated_local_images(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"synthetic image")
    client = RecordingCodexClient(Settings(brain_mode="codex"))

    await client.generate_text(
        developer_instructions="Observa la imagen.",
        user_input="Describe",
        model="gpt-5.6-luna",
        effort="high",
        local_image_paths=(image_path,),
    )

    turn_input = client.requests[1][1]["input"]
    assert turn_input == [
        {"type": "text", "text": "Describe"},
        {"type": "localImage", "path": str(image_path.resolve())},
    ]


@pytest.mark.asyncio
async def test_codex_rejects_unsupported_local_image_extension(tmp_path) -> None:
    image_path = tmp_path / "secret.txt"
    image_path.write_text("not an image", encoding="utf-8")
    client = RecordingCodexClient(Settings(brain_mode="codex"))

    with pytest.raises(CodexAppServerError, match="formato no permitido"):
        await client.generate_text(
            developer_instructions="Observa.",
            user_input="Describe",
            model="gpt-5.6-luna",
            effort="high",
            local_image_paths=(image_path,),
        )


@pytest.mark.asyncio
async def test_codex_rejects_invalid_structured_output() -> None:
    client = RecordingCodexClient(Settings(brain_mode="codex"), answer="incompleto")

    with pytest.raises(CodexAppServerError, match="decision incompleta"):
        await client.generate_json(
            developer_instructions="Responde JSON.",
            user_input="Comprueba",
            model="gpt-5.6-luna",
            effort="medium",
            output_schema={"type": "object"},
        )


@pytest.mark.asyncio
async def test_codex_never_falls_back_to_a_different_model_or_effort() -> None:
    client = RecordingCodexClient(Settings(brain_mode="codex"))
    await client.start()

    with pytest.raises(CodexAppServerError, match="no esta disponible"):
        client.resolve_model("gpt-6.1-sol")
    with pytest.raises(CodexAppServerError, match="no admite"):
        client.resolve_effort("gpt-5.6-luna", "ultra")


@pytest.mark.asyncio
async def test_coding_task_is_confined_to_exact_project_without_network(tmp_path) -> None:
    project = tmp_path / "confirmed-project"
    project.mkdir()
    client = RecordingCodexClient(
        Settings(project_root=tmp_path, brain_mode="codex", codex_coding_timeout=600),
        coding_server=True,
    )

    answer = await client.run_coding_task(project, "Agrega una prueba unitaria")

    thread = client.requests[0][1]
    turn = client.requests[1][1]
    resolved = str(project.resolve())
    assert answer == "Respuesta segura."
    assert thread["cwd"] == resolved
    assert thread["permissions"] == "jarvis-project-only"
    assert "sandbox" not in thread
    assert thread["approvalPolicy"] == "never"
    assert "tarea confirmada" in thread["developerInstructions"]
    assert turn["cwd"] == resolved
    assert turn["permissions"] == "jarvis-project-only"
    assert "sandboxPolicy" not in turn


@pytest.mark.asyncio
async def test_regular_client_delegates_coding_to_a_disposable_server(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "confirmed-project"
    project.mkdir()
    observed: dict[str, Any] = {}

    async def fake_turn(self, **kwargs):
        observed["coding_server"] = self._coding_server
        observed["cwd"] = kwargs["cwd"]
        return "Tarea terminada."

    async def fake_close(self):
        observed["closed"] = self._coding_server

    monkeypatch.setattr(CodexAppServerClient, "_run_ephemeral_turn", fake_turn)
    monkeypatch.setattr(CodexAppServerClient, "close", fake_close)
    client = CodexAppServerClient(Settings(project_root=tmp_path, brain_mode="codex"))

    answer = await client.run_coding_task(project, "Agrega una prueba unitaria")

    assert answer == "Tarea terminada."
    assert observed == {
        "coding_server": True,
        "cwd": project.resolve(),
        "closed": True,
    }


def test_coding_server_uses_an_isolated_process_configuration() -> None:
    normal = CodexAppServerClient(Settings(brain_mode="codex"))
    coding = CodexAppServerClient(Settings(brain_mode="codex"), coding_server=True)

    normal_arguments = normal._app_server_arguments()
    coding_arguments = coding._app_server_arguments()

    assert normal_arguments == ("app-server", "--listen", "stdio://")
    assert "capabilities" not in normal._initialize_parameters()
    assert coding._initialize_parameters()["capabilities"] == {"experimentalApi": True}
    assert "--strict-config" in coding_arguments
    overrides = [
        coding_arguments[index + 1]
        for index, value in enumerate(coding_arguments[:-1])
        if value == "--config"
    ]
    assert 'default_permissions="jarvis-project-only"' in overrides
    assert 'web_search="disabled"' in overrides
    profile = next(value for value in overrides if value.startswith("permissions."))
    assert 'extends=":workspace"' in profile
    assert '":root"="read"' in profile
    assert '"**/.env"="deny"' in profile
    assert "network={enabled=false}" in profile
