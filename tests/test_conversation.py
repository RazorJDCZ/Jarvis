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
        self.superseded_sessions: list[str] = []
        self.contexts: list[tuple[dict[str, str], ...]] = []

    async def try_handle(
        self,
        _session_id: str,
        _message: str,
        *,
        remote: bool = False,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> ActionOutcome | None:
        del remote
        self.contexts.append(conversation_context)
        return self.outcome

    def reset(self, session_id: str) -> None:
        self.reset_sessions.append(session_id)

    def supersede_pending(self, session_id: str) -> bool:
        self.superseded_sessions.append(session_id)
        return True

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


class RejectingVerifier:
    async def verify(self, _message: str) -> VerificationResult | None:
        raise AssertionError("No se debe buscar información pública sobre una persona privada")


class FixedProfileStore:
    @staticmethod
    def system_context() -> str:
        return "- Su nombre preferido es Juandi.\n- Su novia se llama Alex."

    @staticmethod
    def answer(_message: str) -> None:
        return None


class SelectiveProfileStore:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def context_for(self, message: str) -> str:
        self.messages.append(message)
        return "- Montoya es un amigo tranquilo, deportista, dedicado al BMX y a ser DJ."

    @staticmethod
    def system_context() -> str:
        raise AssertionError("Debe usarse la recuperación temática del perfil")

    @staticmethod
    def answer(_message: str) -> None:
        return None

    @staticmethod
    def is_person_reference(message: str) -> bool:
        return "montoya" in message.casefold()


class SelfProfileStore:
    @staticmethod
    def context_for(_message: str) -> str:
        raise AssertionError("El análisis propio debe pedir el contexto completo dedicado")

    @staticmethod
    def self_analysis_context() -> str:
        return (
            "[ESTUDIOS] Estudia Computación en la USFQ.\n"
            "[PROYECTOS] Desarrolla Jarvis y Appa.\n"
            "[RUTINA] Estudia, trabaja, entrena y descansa con videojuegos.\n"
            "[OBJETIVOS] Quiere graduarse y construir un perfil profesional competitivo."
        )
    @staticmethod
    def self_summary() -> str:
        return "Te llamas Juan Diego y estudias Computación en la USFQ."

    @staticmethod
    def answer(message: str) -> str | None:
        return (
            "Te llamas Juan Diego y estudias Computación en la USFQ."
            if "quién soy" in message.casefold()
            else None
        )

    @staticmethod
    def is_person_reference(_message: str) -> bool:
        return False

    @staticmethod
    def is_self_reference(message: str) -> bool:
        normalized = message.casefold()
        return any(
            marker in normalized
            for marker in (
                "mí",
                "analízame",
                "soy",
                "cómo soy",
                "cómo me ves",
                "cómo me percibes",
                "mi personalidad",
                "mi perfil",
                "mis metas",
                "mis fortalezas",
                "juan diego",
            )
        )


class ComposedSelfProfileStore(SelfProfileStore):
    @staticmethod
    def self_analysis_answer(message: str, *, deep_analysis: bool = False) -> str:
        mode = "profundo" if deep_analysis else "normal"
        return f"Análisis personal {mode} y sustentado para: {message}"


class ComposedPersonProfileStore(SelectiveProfileStore):
    @staticmethod
    def person_analysis_answer(message: str, *, deep_analysis: bool = False) -> str:
        mode = "profundo" if deep_analysis else "normal"
        return f"Análisis de persona {mode} y sustentado para: {message}"


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
async def test_profile_context_is_selected_for_the_current_message() -> None:
    brain = RecordingBrain()
    profile = SelectiveProfileStore()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=profile,
    )

    await service.reply("a", "¿Qué plan tranquilo podría hacer con Montoya?")

    assert profile.messages == ["¿Qué plan tranquilo podría hacer con Montoya?"]
    assert "dedicado al BMX" in brain.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_private_person_notes_reach_the_model_as_context_not_a_literal_answer() -> None:
    brain = RecordingBrain()
    profile = SelectiveProfileStore()
    service = ConversationService(
        Settings(information_verification_enabled=True, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=RejectingVerifier(),
        profile_store=profile,
    )

    reply = await service.reply("a", "¿Quién es Montoya?")

    assert reply.provider == "recording"
    assert reply.text == "respuesta 1"
    assert "dedicado al BMX" in brain.calls[0][0]["content"]
    assert "EVIDENCIA_PERSONAL_PRIVADA" in brain.calls[0][0]["content"]
    assert "Eres JARVIS, el asistente personal privado" in brain.calls[0][0]["content"]
    assert brain.calls[0][-1]["content"] == "¿Quién es Montoya?"


@pytest.mark.asyncio
async def test_analytical_question_offers_deep_mode_and_confirmation_replays_request() -> None:
    brain = RecordingBrain()
    actions = RecordingActions()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        actions,
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    offer = await service.reply("a", "¿Qué opinas de la personalidad de Montoya?")
    reply = await service.reply("a", "Sí, profundiza")

    assert offer.provider == "analysis-confirmation"
    assert "análisis profundo" in offer.text
    assert brain.calls[0][-1]["content"] == "¿Qué opinas de la personalidad de Montoya?"
    assert "exactamente cuatro párrafos" in brain.calls[0][0]["content"]
    assert actions.contexts == []
    assert actions.superseded_sessions == ["a", "a"]
    assert reply.provider == "recording"


@pytest.mark.asyncio
async def test_natural_private_person_reflection_also_offers_deep_mode() -> None:
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        RecordingBrain(),
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    reply = await service.reply("a", "Cuéntame sobre Montoya")

    assert reply.provider == "analysis-confirmation"
    assert "análisis profundo" in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision_phrase",
    (
        "Sí, por favor, quiero que profundices mucho más en ese análisis",
        "Claro, dame una respuesta larga y detallada",
        "Quiero la versión profunda",
        "Listo, continúa con más detalle",
    ),
)
async def test_natural_deep_confirmation_replays_current_person_request(
    decision_phrase: str,
) -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    await service.reply("a", "Cuéntame sobre Montoya")
    reply = await service.reply("a", decision_phrase)

    assert reply.provider == "recording"
    assert brain.calls[0][-1]["content"] == "Cuéntame sobre Montoya"
    assert "exactamente cuatro párrafos" in brain.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_person_analysis_excludes_old_conversation_after_mode_choice() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )
    await service.reply("a", "Explícame un tema antiguo que no tiene relación")
    await service.reply("a", "¿Qué opinas de la personalidad de Montoya?")

    reply = await service.reply(
        "a",
        "Sí, quiero que profundices bastante en la respuesta sobre él",
    )

    current_call = brain.calls[-1]
    assert reply.provider == "recording"
    assert len(current_call) == 2
    assert current_call[-1]["content"] == "¿Qué opinas de la personalidad de Montoya?"
    assert all("tema antiguo" not in item["content"] for item in current_call)
    assert all("respuesta 1" not in item["content"] for item in current_call)


@pytest.mark.asyncio
async def test_typoed_normal_choice_cannot_resume_the_previous_topic() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )
    await service.reply("a", "¿Tú crees que Biotecnología es una gran carrera?")
    await service.reply("a", "Cuéntame sobre Montoya")

    reply = await service.reply("a", "No, dame la version nomal")

    current_call = brain.calls[-1]
    assert reply.provider == "recording"
    assert len(current_call) == 2
    assert current_call[-1]["content"] == "Cuéntame sobre Montoya"
    assert "exactamente cuatro párrafos" not in current_call[0]["content"]
    assert all("Biotecnología" not in item["content"] for item in current_call)


@pytest.mark.asyncio
async def test_grounded_person_composer_handles_typoed_choice_without_model_latency() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=ComposedPersonProfileStore(),
    )

    offer = await service.reply("a", "Cuéntame sobre Montoya")
    reply = await service.reply("a", "No, dame la version nomal")

    assert offer.provider == "analysis-confirmation"
    assert reply.provider == "personal-analysis"
    assert reply.text == "Análisis de persona normal y sustentado para: Cuéntame sobre Montoya"
    assert brain.calls == []


@pytest.mark.asyncio
async def test_ambiguous_analysis_choice_keeps_pending_request_until_clarified() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )
    await service.reply("a", "Cuéntame sobre Montoya")

    unclear = await service.reply("a", "Tal vez algo detallado, no sé")
    final = await service.reply("a", "Prefiero algo corto y directo")

    assert unclear.provider == "analysis-confirmation"
    assert "No me quedó claro" in unclear.text
    assert final.provider == "recording"
    assert brain.calls[0][-1]["content"] == "Cuéntame sobre Montoya"
    assert "exactamente cuatro párrafos" not in brain.calls[0][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    (
        "¿Qué sabes de mí?",
        "Cuéntame sobre mí",
        "Jarvis, analízame",
        "¿Cómo soy según lo que sabes?",
        "¿Cómo me ves?",
        "¿Cómo me percibes?",
        "¿Qué clase de persona crees que soy?",
        "¿Cómo dirías que soy?",
        "Analiza mi perfil profesional",
        "¿Qué opinas de mis metas y prioridades?",
        "¿Qué impresión tienes de Juan Diego?",
        "¿Cuáles crees que son mis fortalezas y debilidades?",
    ),
)
async def test_self_reflection_phrasings_offer_analysis_instead_of_reciting_profile(
    phrase: str,
) -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=True, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=RejectingVerifier(),
        profile_store=SelfProfileStore(),
    )

    reply = await service.reply("self", phrase)

    assert reply.provider == "analysis-confirmation"
    assert "análisis profundo" in reply.text
    assert brain.calls == []


@pytest.mark.asyncio
async def test_declined_self_deep_mode_uses_dedicated_complete_profile_prompt() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=True, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=RejectingVerifier(),
        profile_store=SelfProfileStore(),
    )

    await service.reply("self", "¿Qué sabes de mí?")
    reply = await service.reply("self", "No, dame la versión normal")

    prompt = brain.calls[0][0]["content"]
    assert reply.provider == "recording"
    assert "EVIDENCIA_PERSONAL_PROPIA" in prompt
    assert "Desarrolla Jarvis y Appa" in prompt
    assert "No recites el perfil" in prompt
    assert "seis a nueve oraciones" in prompt
    assert "EVIDENCIA_VERIFICADA" not in prompt
    assert brain.calls[0][-1]["content"] == "¿Qué sabes de mí?"


@pytest.mark.asyncio
async def test_explicit_deep_self_analysis_uses_extended_bounded_prompt() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelfProfileStore(),
    )

    reply = await service.reply("self", "Analízame a fondo")

    prompt = brain.calls[0][0]["content"]
    assert reply.provider == "recording"
    assert "entre cinco y siete párrafos" in prompt
    assert "500 y 750 palabras" in prompt
    assert len(brain.calls) == 1


@pytest.mark.asyncio
async def test_grounded_self_composer_bypasses_freeform_model_after_confirmation() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=True, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=RejectingVerifier(),
        profile_store=ComposedSelfProfileStore(),
    )

    offer = await service.reply("self", "¿Qué sabes de mí?")
    reply = await service.reply("self", "Sí, profundiza")

    assert offer.provider == "analysis-confirmation"
    assert reply.provider == "personal-analysis"
    assert reply.text == "Análisis personal profundo y sustentado para: ¿Qué sabes de mí?"
    assert brain.calls == []


@pytest.mark.asyncio
async def test_self_identity_question_remains_factual_and_bypasses_model() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=True, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=RejectingVerifier(),
        profile_store=SelfProfileStore(),
    )

    reply = await service.reply("self", "¿Quién soy?")

    assert reply.provider == "personal-profile"
    assert reply.text == "Te llamas Juan Diego y estudias Computación en la USFQ."
    assert brain.calls == []


@pytest.mark.asyncio
async def test_deep_analysis_can_be_declined_for_a_normal_model_answer() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    await service.reply("a", "Analiza la personalidad de Montoya")
    reply = await service.reply("a", "No, dame la versión normal")

    assert reply.provider == "recording"
    assert brain.calls[0][-1]["content"] == "Analiza la personalidad de Montoya"
    assert "exactamente cuatro párrafos" not in brain.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_explicit_deep_analysis_does_not_ask_twice() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    reply = await service.reply("a", "Analiza a fondo la personalidad de Montoya")

    assert reply.provider == "recording"
    assert len(brain.calls) == 1
    assert "exactamente cuatro párrafos" in brain.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_deep_analysis_offer_can_be_disabled() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(
            information_verification_enabled=False,
            memory_enabled=False,
            deep_analysis_confirmation_enabled=False,
        ),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    reply = await service.reply("a", "¿Qué opinas de la personalidad de Montoya?")

    assert reply.provider == "recording"
    assert "exactamente cuatro párrafos" not in brain.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_screen_analysis_still_goes_to_the_action_engine() -> None:
    outcome = ActionOutcome(ActionStatus.COMPLETED, "Monitor analizado")
    service = ConversationService(
        Settings(memory_enabled=False),
        RecordingBrain(),
        RecordingActions(outcome),
    )

    reply = await service.reply("a", "Analiza lo que ves en el monitor uno")

    assert reply.provider == "action-engine"
    assert reply.action is outcome


@pytest.mark.asyncio
async def test_reset_discards_a_pending_deep_analysis() -> None:
    brain = RecordingBrain()
    service = ConversationService(
        Settings(information_verification_enabled=False, memory_enabled=False),
        brain,
        RecordingActions(),
        verifier=FixedVerifier(None),
        profile_store=SelectiveProfileStore(),
    )

    await service.reply("a", "Analiza la personalidad de Montoya")
    service.reset("a")
    reply = await service.reply("a", "Sí, profundiza")

    assert reply.provider == "recording"
    assert brain.calls[0][-1]["content"] == "Sí, profundiza"
    assert "exactamente cuatro párrafos" not in brain.calls[0][0]["content"]


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


def test_private_person_factual_sanitizer_removes_unsupported_connective_claims() -> None:
    response = (
        "Paula es tu amiga cercana y se graduó de Mercados Internacionales, lo cual explica su "
        "rol natural en las fiestas. Por lo que me has contado, parece muy carismática."
    )

    cleaned = ConversationService._sanitize_private_person_factual(response)

    assert cleaned == "Paula es tu amiga cercana y se graduó de Mercados Internacionales."


def test_private_person_factual_sanitizer_removes_shared_context_and_missing_data_filler() -> None:
    response = (
        "Daniela estudia Jurisprudencia en el contexto académico compartido con todos ustedes. "
        "No hay más datos disponibles sobre ella."
    )

    cleaned = ConversationService._sanitize_private_person_factual(response)

    assert cleaned == "Daniela estudia Jurisprudencia."


def test_private_person_factual_sanitizer_removes_inference_sentences_and_extra_clauses() -> None:
    response = (
        "Emi es tímida y tiene una vibra ligera que contrasta con su reserva. "
        "Parece tener mucho equilibrio emocional. Martina es tu amiga que te ha descrito como "
        "buena persona cuando lo necesita."
    )

    cleaned = ConversationService._sanitize_private_person_factual(response)

    assert cleaned == (
        "Emi es tímida y tiene una vibra ligera. "
        "Martina es tu amiga que has descrito como buena persona."
    )


def test_private_person_factual_sanitizer_normalizes_pronouns_and_more_filler() -> None:
    response = (
        "Nahir tiene una relación con ti. Esta definición se basa en el perfil. "
        "Juanma escucha muy bien sin necesidad de grandes gestos o dramas. "
        "Lo único concreto sobre Washo es que se graduó de Ingeniería Automotriz."
    )

    cleaned = ConversationService._sanitize_private_person_factual(response)

    assert cleaned == "Nahir tiene una relación contigo. Juanma escucha muy bien."


def test_private_person_factual_sanitizer_repairs_unambiguous_relationship_grammar() -> None:
    response = (
        "Nahir es una de tus novias. Analiz es una amiga a quien también llamamos Anita. "
        "Martina es tu amiga con quien has compartido que es buena. Paula es tu amiga y la "
        "describe como fiestera. No se detalla nada más sobre Martina."
    )

    cleaned = ConversationService._sanitize_private_person_factual(response)

    assert cleaned == (
        "Nahir es tu novia. Analiz es una amiga a quien también llamas Anita. "
        "Martina es tu amiga de quien me contaste que es buena. "
        "Paula es tu amiga y la describes como fiestera."
    )


def test_private_person_normal_analysis_sanitizer_removes_extra_causal_claims() -> None:
    response = (
        "Samy se graduó de Gastronomía, lo cual explica que cocine bien. "
        "Chema estudia Administración, lo cual refleja su energía social. "
        "Paula te ha apoyado en varias ocasiones y esto puede sugerir cercanía."
    )

    cleaned = ConversationService._sanitize_private_person_analysis(response)

    assert cleaned == (
        "Samy se graduó de Gastronomía. Chema estudia Administración. "
        "Paula te ha apoyado y esto puede sugerir cercanía."
    )
