from __future__ import annotations

import pytest

from jarvis.actions.models import ActionOutcome, ActionStatus
from jarvis.config import Settings
from jarvis.schemas import ProviderStatus
from jarvis.services.conversation import ConversationService
from jarvis.services.information import VerificationResult


class RecordingBrain:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def status(self) -> ProviderStatus:
        return ProviderStatus(available=True, name=self.name, detail="ok")

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return f"respuesta {len(self.calls)}"


class FollowUpBrain(RecordingBrain):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return "La capital de Ecuador es Quito. ¿Hay algo más en lo que pueda ayudarte?"


class PointedQuestionBrain(RecordingBrain):
    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return "Suena como un plan tranquilo. ¿A qué juego están pensando jugar?"


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


class FixedVerifier:
    def __init__(self, result: VerificationResult | None) -> None:
        self.result = result

    async def verify(self, _message: str) -> VerificationResult | None:
        return self.result


class FixedProfileStore:
    @staticmethod
    def system_context() -> str:
        return "- Su nombre preferido es Juandi.\n- Su novia se llama Alex."

    @staticmethod
    def answer(_message: str) -> None:
        return None


@pytest.mark.asyncio
async def test_history_is_sent_to_brain_and_capped() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(max_history_messages=2, safe_actions_enabled=False, memory_enabled=False),
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
        Settings(max_sessions=2, safe_actions_enabled=False, memory_enabled=False),
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
        Settings(
            max_sessions=0,
            max_history_messages=0,
            safe_actions_enabled=False,
            memory_enabled=False,
        ),
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
    service = ConversationService(
        Settings(safe_actions_enabled=False, memory_enabled=False),
        brain,
        actions,
    )
    await service.reply("a", "hola")

    answer = await service.reply("a", "dime la hora")
    reset = await service.reply("a", "olvida esta conversación")

    assert answer.provider == "safe-command"
    assert reset.provider == "safe-command"
    assert len(brain.calls) == 1
    assert "a" not in service._history
    assert actions.reset_sessions == ["a"]


@pytest.mark.asyncio
async def test_safe_command_precedes_an_action_false_positive() -> None:
    outcome = ActionOutcome(ActionStatus.BLOCKED, "Bloqueado")
    service = ConversationService(
        Settings(memory_enabled=False),
        RecordingBrain(),
        RecordingActions(outcome),
    )

    reply = await service.reply("a", "borra la conversación")

    assert reply.provider == "safe-command"
    assert "contexto temporal" in reply.text


@pytest.mark.asyncio
async def test_action_engine_bypasses_language_model() -> None:
    brain = RecordingBrain()
    outcome = ActionOutcome(ActionStatus.COMPLETED, "Aplicación abierta")
    service = ConversationService(
        Settings(memory_enabled=False),
        brain,
        RecordingActions(outcome),
    )

    reply = await service.reply("a", "abre calculadora")

    assert reply.provider == "action-engine"
    assert reply.action is outcome
    assert brain.calls == []


@pytest.mark.asyncio
async def test_verified_direct_answer_bypasses_language_model() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(
            VerificationResult("Según Open-Meteo, en Quito hay 17 grados Celsius.")
        ),
        profile_store=FixedProfileStore(),
    )

    reply = await service.reply("a", "temperatura en Quito")

    assert reply.provider == "verified-information"
    assert "Open-Meteo" in reply.text
    assert brain.calls == []


@pytest.mark.asyncio
async def test_profile_and_evidence_are_added_only_to_system_prompt() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(
            VerificationResult(evidence="Fuente: Wikipedia. Ecuador está en América del Sur.")
        ),
        profile_store=FixedProfileStore(),
    )

    await service.reply("a", "¿Dónde está Ecuador?")

    system_prompt = brain.calls[0][0]["content"]
    assert "Su novia se llama Alex" in system_prompt
    assert "EVIDENCIA_VERIFICADA" in system_prompt
    assert "No termines cada respuesta con una" in system_prompt
    assert "Alex" not in brain.calls[0][1]["content"]


@pytest.mark.asyncio
async def test_generic_follow_up_question_is_removed_from_model_answer() -> None:
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        FollowUpBrain(),
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=FixedProfileStore(),
    )

    reply = await service.reply("a", "Dime la capital de Ecuador")

    assert reply.text == "La capital de Ecuador es Quito."


@pytest.mark.asyncio
async def test_pointed_contextual_question_is_preserved() -> None:
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        PointedQuestionBrain(),
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=FixedProfileStore(),
    )

    reply = await service.reply("a", "Esta noche jugaré algo con mis amigos")

    assert reply.text.endswith("¿A qué juego están pensando jugar?")


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            "La recursión necesita un caso base. ¿Te gustaría ver algún ejemplo práctico?",
            "La recursión necesita un caso base.",
        ),
        (
            "Hollow Knight tiene una atmósfera especial. Ya tienes todo el contexto listo para "
            "seguir hablando sobre ello cuando quieras.",
            "Hollow Knight tiene una atmósfera especial.",
        ),
        (
            "Suena como un buen plan. ¿Necesitas ayuda para organizarlo o solo querías contarlo?",
            "Suena como un buen plan.",
        ),
        (
            "Eso demuestra bastante constancia. Si necesitas ayuda para ajustar algo, solo dime "
            "qué quieres revisar.",
            "Eso demuestra bastante constancia.",
        ),
        (
            "Se nota que disfrutas resolver esos obstáculos. Dado que te divierte el proceso, "
            "quizás podrías considerar si hay un fragmento para analizarlo juntos.",
            "Se nota que disfrutas resolver esos obstáculos.",
        ),
    ],
)
def test_additional_generic_voice_closings_are_removed(response: str, expected: str) -> None:
    assert ConversationService._trim_generic_follow_up(response) == expected
