from __future__ import annotations

import pytest

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus
from jarvis.services.conversation import ConversationService


class RecordingBrain:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def status(self) -> ProviderStatus:
        return ProviderStatus(available=True, name=self.name, detail="ok")

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return f"respuesta {len(self.calls)}"


@pytest.mark.asyncio
async def test_history_is_sent_to_brain_and_capped() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(max_history_messages=2, safe_actions_enabled=False),
        brain,
    )

    await service.reply("a", "primero")
    reply = await service.reply("a", "segundo")

    assert reply.provider == "recording"
    assert [item["content"] for item in brain.calls[-1][1:]] == ["respuesta 1", "segundo"]


@pytest.mark.asyncio
async def test_oldest_session_is_evicted_at_limit() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(max_sessions=2, safe_actions_enabled=False),
        brain,
    )

    await service.reply("a", "uno")
    await service.reply("b", "dos")
    await service.reply("c", "tres")

    assert list(service._history) == ["b", "c"]


@pytest.mark.asyncio
async def test_nonpositive_limits_are_safely_clamped() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(max_sessions=0, max_history_messages=0, safe_actions_enabled=False),
        brain,
    )

    await service.reply("a", "uno")
    await service.reply("b", "dos")

    assert list(service._history) == ["b"]
    assert len(service._history["b"]) == 1


@pytest.mark.asyncio
async def test_safe_command_bypasses_brain_and_can_reset_history() -> None:
    brain = RecordingBrain()
    service = ConversationService(Settings(safe_actions_enabled=False), brain)
    await service.reply("a", "hola")

    answer = await service.reply("a", "dime la hora")
    reset = await service.reply("a", "olvida esta conversación")

    assert answer.provider == "safe-command"
    assert reset.provider == "safe-command"
    assert len(brain.calls) == 1
    assert "a" not in service._history
