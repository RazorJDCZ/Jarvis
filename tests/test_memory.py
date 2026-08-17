from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.actions.models import ActionOutcome
from jarvis.config import Settings
from jarvis.schemas import ProviderStatus
from jarvis.services.conversation import ConversationService
from jarvis.services.information import VerificationResult
from jarvis.services.memory import (
    MemoryCandidate,
    MemoryExtractor,
    MemoryService,
    MemoryStore,
)


def memory_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(project_root=tmp_path, memory_enabled=True, **overrides)


def test_memory_store_uses_private_sqlite_database_and_upserts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")

    first = store.upsert(MemoryCandidate("location:home", "Vive en Quito.", "ubicacion"))
    second = store.upsert(MemoryCandidate("location:home", "Vive en Cuenca.", "ubicacion"))

    assert store.available is True
    assert first is not None and second is not None
    assert store.path.is_file()
    assert len(store.list_entries()) == 1
    assert store.list_entries()[0].content == "Vive en Cuenca."


def test_memory_store_prunes_old_entries_to_configured_limit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3", max_entries=10)

    for index in range(12):
        store.upsert(MemoryCandidate(f"fact:{index}", f"Dato número {index}.", "dato"))

    entries = store.list_entries(100)
    assert len(entries) == 10
    assert all(entry.memory_key not in {"fact:0", "fact:1"} for entry in entries)


@pytest.mark.parametrize(
    ("message", "category", "fragment"),
    [
        ("Vivo en Quito", "ubicacion", "Quito"),
        ("Estudio Ingeniería en Computación", "estudios", "Ingeniería"),
        ("Me gusta tocar el ukelele", "preferencia", "ukelele"),
        ("No me gustan las discotecas", "preferencia", "discotecas"),
        ("Prefiero planes tranquilos", "preferencia", "planes tranquilos"),
        ("Quiero aprender japonés", "objetivo", "japonés"),
        ("Estoy desarrollando mi propio Jarvis", "proyecto", "su propio Jarvis"),
        ("Mi perro se llama Tobi", "dato_personal", "Tobi"),
    ],
)
def test_implicit_memory_extraction_is_selective(
    message: str,
    category: str,
    fragment: str,
) -> None:
    candidate = MemoryExtractor.implicit_candidate(message)

    assert candidate is not None
    assert candidate.category == category
    assert fragment in candidate.content


@pytest.mark.parametrize(
    "message",
    [
        "¿Qué me gusta?",
        "¿Dónde vivo?",
        "Estoy cansado hoy",
        "Abre la calculadora",
        "Mi contraseña es hunter2",
        "Mi token es abc123",
    ],
)
def test_questions_transient_state_commands_and_secrets_are_not_learned(message: str) -> None:
    assert MemoryExtractor.implicit_candidate(message) is None


def test_relevant_retrieval_and_physical_forget(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.upsert(MemoryCandidate("like:music", "Le gusta tocar el ukelele.", "preferencia"))
    store.upsert(MemoryCandidate("like:games", "Le gustan los videojuegos.", "preferencia"))
    store.upsert(MemoryCandidate("project:jarvis", "Está trabajando en Jarvis.", "proyecto"))

    relevant = store.relevant("Hablemos del ukelele")
    projects = store.relevant("¿Qué sabes de mis proyectos?")
    removed = store.forget_best("tocar ukelele")

    assert [entry.memory_key for entry in relevant] == ["like:music"]
    assert [entry.memory_key for entry in projects] == ["project:jarvis"]
    assert removed is not None and removed.memory_key == "like:music"
    assert {entry.memory_key for entry in store.list_entries()} == {
        "like:games",
        "project:jarvis",
    }


def test_recent_conversations_are_bounded_filterable_and_resettable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3", max_turns=2)

    assert store.add_turn("a", "uno", "respuesta uno") is True
    assert store.add_turn("b", "dos", "respuesta dos") is True
    assert store.add_turn("c", "tres", "respuesta tres") is True

    assert store.recent_turns(limit=10) == (
        ("dos", "respuesta dos"),
        ("tres", "respuesta tres"),
    )
    assert store.recent_turns(exclude_session="c", limit=10) == (("dos", "respuesta dos"),)
    assert store.stats().sessions == 2
    assert store.stats().turns == 2
    store.clear_session("b")
    assert store.recent_turns(limit=10) == (("tres", "respuesta tres"),)
    assert store.stats().sessions == 1


def test_identical_consecutive_exchange_is_not_stored_twice(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")

    assert store.add_turn("a", "Hola Jarvis", "Hola, Juandi.") is True
    assert store.add_turn("a", "  hola   jarvis ", "HOLA, JUANDI.") is False
    assert store.add_turn("a", "¿Cómo estás?", "Muy bien.") is True

    assert store.stats().sessions == 1
    assert store.stats().turns == 2


def test_sensitive_conversation_is_never_persisted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")

    saved = store.add_turn("a", "Mi contraseña es secreta", "Entendido")

    assert saved is False
    assert store.counts() == (0, 0)


def test_memory_voice_commands_require_confirmation_for_total_clear(tmp_path: Path) -> None:
    service = MemoryService(memory_settings(tmp_path))
    remembered = service.handle("a", "Recuerda que mi color favorito es el azul")

    request = service.handle("a", "Borra toda tu memoria")
    wrong_session = service.handle("b", "confirmo borrar toda mi memoria")
    confirmed = service.handle("a", "confirmo borrar toda mi memoria")

    assert remembered is not None and "memoria local" in remembered
    assert service.store.counts()[0] == 0
    assert request is not None and "Si estás seguro" in request
    assert wrong_session is None
    assert confirmed is not None and "Eliminé" in confirmed


def test_memory_voice_commands_list_and_forget_one_fact(tmp_path: Path) -> None:
    service = MemoryService(memory_settings(tmp_path))
    service.handle("a", "Recuerda que mi color favorito es el azul")

    listed = service.handle("a", "¿Qué recuerdas de mí?", "Te llamas Juandi.")
    forgotten = service.handle("a", "Olvida que mi color favorito es azul")

    assert listed is not None and "Juandi" in listed and "color favorito" in listed
    assert forgotten is not None and "Olvidé" in forgotten
    assert service.store.list_entries() == ()


def test_memory_command_detection_does_not_capture_conversation_reset(tmp_path: Path) -> None:
    service = MemoryService(memory_settings(tmp_path))

    assert service.is_command("a", "Recuerda que me gusta el azul") is True
    assert service.is_command("a", "Borra toda tu memoria") is True
    assert service.is_command("a", "¿Qué sabes de mí?") is False
    assert service.is_command("a", "¿Qué recuerdas de mí?") is True
    assert service.is_command("a", "Borra la conversación") is False
    assert service.is_command("a", "Olvida esta conversación") is False


def test_memory_rejects_explicit_secret(tmp_path: Path) -> None:
    service = MemoryService(memory_settings(tmp_path))

    response = service.handle("a", "Recuerda que mi contraseña es hunter2")

    assert response is not None and "No guardaré" in response
    assert service.store.list_entries() == ()


def test_disabled_or_corrupt_memory_fails_closed(tmp_path: Path) -> None:
    disabled_path = tmp_path / "disabled.sqlite3"
    disabled = MemoryStore(disabled_path, enabled=False)
    corrupt_path = tmp_path / "corrupt.sqlite3"
    corrupt_path.write_bytes(b"not a sqlite database")
    corrupt = MemoryStore(corrupt_path)

    assert disabled.available is False
    assert disabled_path.exists() is False
    assert corrupt.available is False
    assert corrupt.list_entries() == ()


class MemoryBrain:
    name = "memory-brain"

    def __init__(self, answer: str = "Suena como un proyecto interesante.") -> None:
        self.answer = answer
        self.calls: list[list[dict[str, str]]] = []

    async def status(self) -> ProviderStatus:
        return ProviderStatus(available=True, name=self.name, detail="ok")

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.answer


class NoActions:
    async def try_handle(
        self,
        _session_id: str,
        _message: str,
        *,
        remote: bool = False,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> ActionOutcome | None:
        return None


class ExplodingActions(NoActions):
    async def try_handle(
        self,
        _session_id: str,
        _message: str,
        *,
        remote: bool = False,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> ActionOutcome | None:
        raise AssertionError("El motor de acciones no debe recibir comandos de memoria")

    def reset(self, _session_id: str) -> None:
        return None


class NoVerification:
    async def verify(self, _message: str) -> VerificationResult | None:
        return None


class BasicProfile:
    @staticmethod
    def answer(message: str) -> str | None:
        return "Te llamas Juandi." if message == "que sabes de mi" else None

    @staticmethod
    def system_context() -> str:
        return "- Su nombre preferido es Juandi."


@pytest.mark.asyncio
async def test_conversation_memory_survives_service_restart_and_is_injected_relevantly(
    tmp_path: Path,
) -> None:
    settings = memory_settings(tmp_path, information_verification_enabled=False)
    first_brain = MemoryBrain()
    first = ConversationService(
        settings,
        first_brain,
        NoActions(),
        verifier=NoVerification(),
        profile_store=BasicProfile(),
    )
    await first.reply("old-session", "Me gusta tocar el ukelele")

    second_brain = MemoryBrain("El ukelele te queda muy bien.")
    second = ConversationService(
        settings,
        second_brain,
        NoActions(),
        verifier=NoVerification(),
        profile_store=BasicProfile(),
    )
    await second.reply("new-session", "Hablemos del ukelele")

    system_prompt = second_brain.calls[0][0]["content"]
    assert "RECUERDOS_LOCALES" in system_prompt
    assert "Le gusta tocar el ukelele" in system_prompt
    assert "CONVERSACION_RECIENTE" in system_prompt
    assert "Me gusta tocar el ukelele" in system_prompt


def test_recent_context_excludes_unrelated_people(tmp_path: Path) -> None:
    service = MemoryService(memory_settings(tmp_path))
    service.store.add_turn(
        "old-samy",
        "¿Quién es Sami?",
        "Sami no aparece en el perfil confirmado.",
    )
    service.store.add_turn(
        "old-music",
        "Me gusta tocar el ukelele",
        "Sami también toca un instrumento muy versátil.",
    )
    service.store.add_turn(
        "old-washo",
        "¿Quién es Washo?",
        "Washo es Sami y esta respuesta antigua está equivocada.",
    )

    person_context = service.recent_context("new", "¿Quién es Washo?")
    music_context = service.recent_context("new", "Hablemos del ukelele")

    assert person_context == ""
    assert "Sami" not in music_context
    assert "ukelele" in music_context


@pytest.mark.asyncio
async def test_explicit_memory_command_bypasses_brain_and_reset_keeps_durable_fact(
    tmp_path: Path,
) -> None:
    settings = memory_settings(tmp_path, information_verification_enabled=False)
    brain = MemoryBrain()
    service = ConversationService(
        settings,
        brain,
        ExplodingActions(),
        verifier=NoVerification(),
        profile_store=BasicProfile(),
    )

    reply = await service.reply("a", "Recuerda que mi color favorito es azul")
    service.reset("a")

    assert reply.provider == "local-memory"
    assert brain.calls == []
    assert len(service.memory.store.list_entries()) == 1
    assert service.memory.store.recent_turns() == ()
