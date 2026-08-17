from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import (
    ActionName,
    ActionRisk,
    ActionStatus,
    ExecutionResult,
    PreparedAction,
)
from jarvis.actions.parser import DeterministicActionParser
from jarvis.capabilities.stores import PermissionStore, ReminderStore, TraceStore
from jarvis.capabilities.suite import CapabilitySuite
from jarvis.config import Settings
from jarvis.services.conversation import ConversationService


class NoPlanning:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def plan(self, text: str, _context=()):
        self.calls.append(text)
        raise AssertionError("El parser determinista debía resolver o descartar esta frase")


class FakeBrowser:
    async def status(self):
        return ExecutionResult(True, "ok")


class IsolatedCatalog:
    """Catalog double that cannot touch Windows, a browser, the network or a process."""

    action_names = tuple(action.value for action in ActionName)
    browser = FakeBrowser()

    def __init__(
        self,
        tmp_path: Path,
        result: ExecutionResult | None = None,
    ) -> None:
        database = tmp_path / "isolated-capabilities.sqlite3"
        self.capabilities = SimpleNamespace(
            permissions=PermissionStore(database),
            traces=TraceStore(database),
        )
        self.result = result or ExecutionResult(True, "Acción simulada y verificada")
        self.executed: list[PreparedAction] = []

    @staticmethod
    def prepare(plan) -> PreparedAction:
        risk = {
            ActionName.POINTER_CLICK: ActionRisk.HIGH,
            ActionName.TASK_CREATE: ActionRisk.MEDIUM,
            ActionName.REMINDER_CREATE: ActionRisk.MEDIUM,
        }.get(plan.name, ActionRisk.LOW)
        return PreparedAction(
            plan.name,
            dict(plan.arguments),
            risk,
            f"Simular {plan.name.value}",
            plan.source,
        )

    async def execute(self, action: PreparedAction) -> ExecutionResult:
        self.executed.append(action)
        return self.result

    async def dialog_available(self, _parent_handle: int, _dialog_handle: int) -> bool:
        return True


class FakeBrain:
    name = "fake-brain"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return "Respuesta conversacional, sin ejecutar nada."


class FakeMemory:
    @staticmethod
    def is_command(_session_id: str, _message: str) -> bool:
        return False

    @staticmethod
    def learn(_message: str) -> None:
        return None

    @staticmethod
    def context(_message: str) -> str:
        return ""

    @staticmethod
    def recent_context(_session_id: str, _message: str) -> str:
        return ""

    @staticmethod
    def remember_exchange(_session_id: str, _message: str, _response: str) -> None:
        return None

    @staticmethod
    def reset_session(_session_id: str) -> None:
        return None


class FakeProfile:
    @staticmethod
    def answer(_message: str):
        return None

    @staticmethod
    def context_for(_message: str) -> str:
        return ""

    @staticmethod
    def is_person_reference(_message: str) -> bool:
        return False

    @staticmethod
    def is_self_reference(_message: str) -> bool:
        return False


class FakeVerifier:
    @staticmethod
    async def verify(_message: str):
        return None


def isolated_engine(
    tmp_path: Path,
    *,
    result: ExecutionResult | None = None,
) -> tuple[ActionEngine, IsolatedCatalog, NoPlanning]:
    catalog = IsolatedCatalog(tmp_path, result)
    planner = NoPlanning()
    engine = ActionEngine(
        Settings(
            project_root=tmp_path,
            action_model_planning=False,
            information_verification_enabled=False,
            memory_enabled=False,
        ),
        catalog=catalog,
        planner=planner,
    )
    return engine, catalog, planner


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        (
            "Estoy organizando el día, ¿me puedes crear una tarea para revisar Appa?",
            ActionName.TASK_CREATE,
            {"title": "revisar appa"},
        ),
        (
            "Oye Jarvis, ¿me harías el favor de crear una tarea para terminar Appa?",
            ActionName.TASK_CREATE,
            {"title": "terminar appa"},
        ),
        (
            "Quiero que crees una tarea para llamar a Juanma",
            ActionName.TASK_CREATE,
            {"title": "llamar a juanma"},
        ),
        (
            "Quiero que me recuerdes llamar a Nahir mañana a las 9",
            ActionName.REMINDER_CREATE,
            {"title": "llamar a nahir", "due": "manana a las 9", "recurrence": "none"},
        ),
        (
            "Recuérdame revisar la agenda cada mes a las 9",
            ActionName.REMINDER_CREATE,
            {"title": "revisar la agenda", "due": "hoy a las 9", "recurrence": "monthly"},
        ),
        ("Podrías mostrarme mis recordatorios", ActionName.REMINDER_LIST, {}),
        (
            "Crea una tarea para comprar pan y leche",
            ActionName.TASK_CREATE,
            {"title": "comprar pan y leche"},
        ),
        ("Abre Minecraft", ActionName.APP_OPEN, {"app": "minecraft"}),
        ("Abre el juego Minecraft", ActionName.GAME_LAUNCH, {"game": "minecraft"}),
    ],
)
def test_natural_requests_keep_their_full_intent_without_model_planning(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parser = DeterministicActionParser()

    parsed = parser.parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments
    assert parser.has_agent_intent(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "No quiero que crees una tarea para borrar todo",
        "¿Cómo puedo crear una tarea en Appa?",
        "Sería genial si me recordaras llamar a Nahir mañana",
        "Explícame cómo usar la receta resumen diario",
        "No necesito que abras el juego Minecraft",
        "Quiero hablar sobre mis recordatorios",
        "Quiero saber cómo funcionan las tareas de Appa",
        "¿Me puedes mostrar cómo crear una tarea en Appa?",
        "Quiero que me muestres cómo borrar un recordatorio",
        "¿Podrías enseñarme cómo lanzar un juego?",
    ],
)
def test_meta_negated_and_hypothetical_capability_phrases_never_become_actions(
    phrase: str,
) -> None:
    parser = DeterministicActionParser()

    assert parser.parse(phrase) is None
    assert parser.has_agent_intent(phrase) is False


@pytest.mark.asyncio
async def test_conversation_routes_contextual_tasks_but_keeps_discussion_in_chat(
    tmp_path: Path,
) -> None:
    engine, catalog, planner = isolated_engine(tmp_path)
    brain = FakeBrain()
    service = ConversationService(
        engine.settings,
        brain,
        engine,
        verifier=FakeVerifier(),
        profile_store=FakeProfile(),
        memory=FakeMemory(),
    )

    action_reply = await service.reply(
        "owner",
        "Estoy organizando el día, ¿me puedes crear una tarea para revisar Appa?",
    )
    chat_reply = await service.reply("owner", "Quiero hablar sobre mis recordatorios")

    assert action_reply.provider == "action-engine"
    assert action_reply.action is not None
    assert action_reply.action.name is ActionName.TASK_CREATE
    assert action_reply.action.status is ActionStatus.PENDING
    assert chat_reply.provider == "fake-brain"
    assert len(brain.calls) == 1
    assert catalog.executed == []
    assert planner.calls == []


def test_permission_store_fails_closed_for_unknown_or_malformed_risk(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path / "permissions.sqlite3")
    store.set("volume.change", False, "allow")

    assert store.is_allowed("volume.change", False, "low") is True
    assert store.is_allowed("volume.change", False, " medium ") is True
    assert store.is_allowed("volume.change", False, "critical") is False
    assert store.is_allowed("volume.change", False, "") is False
    assert store.is_allowed("volume.change", False, None) is False
    assert store.is_allowed("volume.change", False, ActionRisk.BLOCKED) is False


@pytest.mark.asyncio
async def test_remembered_permission_is_scoped_to_one_remote_device(tmp_path: Path) -> None:
    engine, catalog, _planner = isolated_engine(tmp_path)

    first = await engine.try_handle(
        "remote:pixel:session-one",
        "sube el volumen",
        remote=True,
    )
    remembered = await engine.try_handle(
        "remote:pixel:session-one",
        "confirma siempre",
        remote=True,
    )
    same_device = await engine.try_handle(
        "remote:pixel:session-two",
        "sube el volumen",
        remote=True,
    )
    other_device = await engine.try_handle(
        "remote:laptop:session-one",
        "sube el volumen",
        remote=True,
    )

    assert first is not None and first.status is ActionStatus.PENDING
    assert remembered is not None and remembered.status is ActionStatus.COMPLETED
    assert remembered.details["permission_remembered"] is True
    assert same_device is not None and same_device.status is ActionStatus.COMPLETED
    assert other_device is not None and other_device.status is ActionStatus.PENDING
    assert len(catalog.executed) == 2
    rules = catalog.capabilities.permissions.list(remote=True)
    assert [rule.action for rule in rules] == ["volume.change@device:pixel"]


@pytest.mark.asyncio
async def test_failed_or_high_risk_actions_never_create_remembered_permissions(
    tmp_path: Path,
) -> None:
    failed_engine, failed_catalog, _ = isolated_engine(
        tmp_path / "failed",
        result=ExecutionResult(False, "Fallo simulado"),
    )
    pending = await failed_engine.try_handle(
        "remote:pixel:one",
        "sube el volumen",
        remote=True,
    )
    assert pending is not None and pending.action_id is not None
    failed = await failed_engine.decide(
        "remote:pixel:one",
        pending.action_id,
        True,
        remember=True,
    )

    high_engine, high_catalog, _ = isolated_engine(tmp_path / "high")
    high_pending = await high_engine.try_handle("local", "haz clic en 10, 20")
    assert high_pending is not None and high_pending.action_id is not None
    high = await high_engine.decide(
        "local",
        high_pending.action_id,
        True,
        remember=True,
    )

    assert failed.status is ActionStatus.FAILED
    assert failed_catalog.capabilities.permissions.list() == ()
    assert high.status is ActionStatus.COMPLETED
    assert "permission_remembered" not in high.details
    assert high_catalog.capabilities.permissions.list() == ()


@pytest.mark.parametrize(
    ("text", "now", "recurrence", "expected"),
    [
        (
            "el 5 de agosto a las 9",
            datetime(2026, 8, 10, 15, tzinfo=UTC),
            "none",
            datetime(2027, 8, 5, 14, tzinfo=UTC),
        ),
        (
            "el 31 a las 9",
            datetime(2026, 4, 30, 15, tzinfo=UTC),
            "none",
            datetime(2026, 5, 31, 14, tzinfo=UTC),
        ),
        (
            "hoy a las 9",
            datetime(2027, 1, 31, 15, tzinfo=UTC),
            "monthly",
            datetime(2027, 2, 28, 14, tzinfo=UTC),
        ),
    ],
)
def test_calendar_recurrence_uses_the_first_valid_future_occurrence(
    text: str,
    now: datetime,
    recurrence: str,
    expected: datetime,
) -> None:
    assert CapabilitySuite.parse_due(text, now=now, recurrence=recurrence) == expected


@pytest.mark.parametrize("text", ["hoy a las 24:00", "el 30 de febrero a las 9"])
def test_invalid_calendar_dates_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        CapabilitySuite.parse_due(
            text,
            now=datetime(2026, 8, 10, 15, tzinfo=UTC),
        )


def test_fired_one_shot_reminder_is_inactive_and_releases_session_capacity(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    store = ReminderStore(
        tmp_path / "reminders.sqlite3",
        clock=lambda: now,
        max_per_session=1,
    )
    first = store.create("owner", "Primero", now - timedelta(minutes=1))

    store.mark_fired(first.reminder_id, "owner", now)
    second = store.create("owner", "Segundo", now + timedelta(hours=1))

    assert [item.reminder_id for item in store.list("owner")] == [second.reminder_id]
    assert store.session_ids() == ("owner",)
    assert store.due("owner") == ()
    history = store.list("owner", include_cancelled=True)
    assert {item.reminder_id for item in history} == {first.reminder_id, second.reminder_id}


class ExplodingActions:
    def __init__(self, traces: TraceStore) -> None:
        self.capabilities = SimpleNamespace(traces=traces)

    async def try_handle(self, *_args, **_kwargs):
        raise RuntimeError("password=never-persist-this")

    @staticmethod
    def supersede_pending(_session_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_conversation_exception_finishes_a_redacted_failed_trace(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "traces.sqlite3")
    settings = Settings(
        project_root=tmp_path,
        memory_enabled=False,
        information_verification_enabled=False,
    )
    service = ConversationService(
        settings,
        FakeBrain(),
        ExplodingActions(traces),
        verifier=FakeVerifier(),
        profile_store=FakeProfile(),
        memory=FakeMemory(),
    )

    with pytest.raises(RuntimeError):
        await service.reply("owner", "abre algo con token=super-secret")

    trace = traces.recent("owner", 1)[0]
    assert trace.status == "failed"
    assert trace.finished_at is not None
    assert "super-secret" not in trace.input_summary
    assert [span.name for span in trace.spans] == ["request.received", "request.failed"]
    assert trace.spans[-1].detail == "RuntimeError"
    assert traces.recent("other", 1) == ()


def test_trace_retention_is_bounded_per_session_without_cross_session_eviction(
    tmp_path: Path,
) -> None:
    clock_value = datetime(2026, 8, 10, tzinfo=UTC)
    store = TraceStore(
        tmp_path / "bounded-traces.sqlite3",
        clock=lambda: clock_value,
        max_records_per_session=10,
    )
    other = store.start("other", "independiente", "chat")
    for index in range(12):
        store.start("owner", f"petición {index}", "chat")

    owner_records = store.recent("owner", 100)

    assert len(owner_records) == 10
    assert {record.input_summary for record in owner_records} == {
        f"petición {index}" for index in range(2, 12)
    }
    assert store.get(other, "other") is not None
    assert store.get(other, "owner") is None


def test_fixed_quito_timezone_is_used_without_external_timezone_data() -> None:
    # This assertion documents the offline fallback contract without touching zoneinfo files.
    due = CapabilitySuite.parse_due(
        "en 30 minutos",
        now=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )

    assert due == datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
