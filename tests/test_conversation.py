from __future__ import annotations

import pytest

from jarvis.actions.models import ActionOutcome, ActionStatus
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


class RecordingActions:
    def __init__(self, outcome: ActionOutcome | None = None) -> None:
        self.outcome = outcome
        self.reset_sessions: list[str] = []

    async def try_handle(self, _session_id: str, _message: str) -> ActionOutcome | None:
        return self.outcome

    def reset(self, session_id: str) -> None:
        self.reset_sessions.append(session_id)

    async def decide(
        self,
        _session_id: str,
        _action_id: str,
        _approve: bool,
    ) -> ActionOutcome:
        return self.outcome or ActionOutcome(ActionStatus.REJECTED, "Nada pendiente")


@pytest.mark.asyncio
async def test_history_is_sent_to_brain_and_capped() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(max_history_messages=2, safe_actions_enabled=False),
        brain,
        RecordingActions(),
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
        RecordingActions(),
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
        RecordingActions(),
    )

    await service.reply("a", "uno")
    await service.reply("b", "dos")

    assert list(service._history) == ["b"]
    assert len(service._history["b"]) == 1


@pytest.mark.asyncio
async def test_safe_command_bypasses_brain_and_can_reset_history() -> None:
    brain = RecordingBrain()
    actions = RecordingActions()
    service = ConversationService(Settings(safe_actions_enabled=False), brain, actions)
    await service.reply("a", "hola")

    answer = await service.reply("a", "dime la hora")
    reset = await service.reply("a", "olvida esta conversación")

    assert answer.provider == "safe-command"
    assert reset.provider == "safe-command"
    assert len(brain.calls) == 1
    assert "a" not in service._history
    assert actions.reset_sessions == ["a"]


@pytest.mark.asyncio
async def test_action_engine_bypasses_language_model() -> None:
    brain = RecordingBrain()
    outcome = ActionOutcome(ActionStatus.COMPLETED, "Aplicación abierta")
    service = ConversationService(
        Settings(),
        brain,
        RecordingActions(outcome),
    )

    reply = await service.reply("a", "abre calculadora")

    assert reply.provider == "action-engine"
    assert reply.action is outcome
    assert brain.calls == []
