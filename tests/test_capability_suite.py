from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from jarvis.actions.models import (
    ActionName,
    ActionPlan,
    ActionRisk,
    ExecutionResult,
    PreparedAction,
    PreparedWorkflow,
)
from jarvis.actions.parser import DeterministicActionParser
from jarvis.capabilities.connectors import AppaConnector, ConnectorRegistry, LocalTaskConnector
from jarvis.capabilities.developer import TestRunResult as DeveloperTestResult
from jarvis.capabilities.gaming import GameInfo
from jarvis.capabilities.suite import CapabilitySuite
from jarvis.capabilities.system import SystemSnapshot
from jarvis.config import Settings


class NeverClipboard:
    def read(self) -> ExecutionResult:
        raise AssertionError("El portapapeles real no debe tocarse en estas pruebas")


class FakeApps:
    def __init__(self) -> None:
        self.launches: list[tuple[str, str]] = []

    def open_game_protocol(self, target: str, name: str) -> ExecutionResult:
        self.launches.append((target, name))
        return ExecutionResult(True, f"Simulado: {name}", {"verified": True})


class FakeCatalog:
    def __init__(self) -> None:
        self.apps = FakeApps()
        self.prepared: list[ActionPlan] = []
        self.workflows: list[PreparedWorkflow] = []

    def prepare(self, plan: ActionPlan) -> PreparedAction:
        self.prepared.append(plan)
        return PreparedAction(
            plan.name,
            dict(plan.arguments),
            ActionRisk.LOW,
            f"Simular {plan.name.value}",
            plan.source,
        )

    async def execute(
        self,
        workflow: PreparedWorkflow,
        *,
        session_id: str,
    ) -> ExecutionResult:
        del session_id
        self.workflows.append(workflow)
        return ExecutionResult(True, "Workflow simulado", {"verified": True})


class NeverVision:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_image_bytes(self, *_args: object, **_kwargs: object) -> ExecutionResult:
        self.calls += 1
        raise AssertionError("Ninguna prueba debe activar visión o cámara")


@dataclass
class FakeDeveloper:
    root: Path
    calls: int = 0

    def roots(self):
        return (SimpleNamespace(name="jarvis", path=self.root),)

    def run_tests(self, _name: str, command: tuple[str, ...]) -> DeveloperTestResult:
        self.calls += 1
        assert command == ("python", "-m", "pytest", "-q")
        return DeveloperTestResult(command, ".", 0, "12 passed", "", False)


class FakeGames:
    def inventory(self) -> tuple[GameInfo, ...]:
        return (GameInfo("123", "Minecraft", "steam", "steam://rungameid/123"),)


class FixedSystemMonitor:
    def sample(self):
        return (
            SystemSnapshot(
                captured_at=1.0,
                cpu_percent=12.5,
                memory_percent=44.0,
                memory_available_gb=8.0,
                disk_percent=61.0,
                disk_free_gb=120.5,
                battery_percent=80.0,
                plugged_in=True,
            ),
            (),
        )


def settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        memory_enabled=False,
        information_verification_enabled=False,
        action_model_planning=False,
        ollama_warmup_enabled=False,
        appa_auto_discover=False,
        steam_roots=str(tmp_path / "no-steam"),
        epic_manifest_roots=str(tmp_path / "no-epic"),
    )


def test_parse_due_uses_quito_timezone_and_rejects_past_times() -> None:
    now = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)  # 10:00 in Quito

    assert CapabilitySuite.parse_due("en 20 minutos", now) == now + timedelta(minutes=20)
    assert CapabilitySuite.parse_due("mañana a las 9", now) == datetime(
        2026, 8, 11, 14, 0, tzinfo=UTC
    )
    assert CapabilitySuite.parse_due("2026-08-11T09:00", now) == datetime(
        2026, 8, 11, 14, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="ya pasó"):
        CapabilitySuite.parse_due("hoy a las 9", now)
    assert CapabilitySuite.parse_due("hoy a las 9", now, "daily") == datetime(
        2026, 8, 11, 14, 0, tzinfo=UTC
    )
    assert CapabilitySuite.parse_task_due("mañana", now) == "2026-08-11"
    assert CapabilitySuite.parse_task_due("mañana a las 9", now) == "2026-08-11"
    assert CapabilitySuite.parse_task_due("el 12 de agosto", now) == "2026-08-12"


def test_parse_due_monthly_clamps_to_last_valid_day() -> None:
    now = datetime(2026, 1, 31, 18, 0, tzinfo=UTC)  # 13:00 in Quito

    assert CapabilitySuite.parse_due("hoy a las 9", now, "monthly") == datetime(
        2026, 2, 28, 14, 0, tzinfo=UTC
    )


def test_parser_calendar_date_is_accepted_by_the_due_parser() -> None:
    parsed = DeterministicActionParser().parse(
        "Jarvis, recuérdame entregar el informe el 12 de agosto a las 9"
    )

    assert parsed is not None and parsed.name is ActionName.REMINDER_CREATE
    due = CapabilitySuite.parse_due(
        str(parsed.arguments["due"]),
        datetime(2026, 8, 10, 15, 0, tzinfo=UTC),
    )
    assert due == datetime(2026, 8, 12, 14, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        ("crea una tarea para revisar Appa", ActionName.TASK_CREATE, {"title": "revisar appa"}),
        (
            "crea una tarea en Appa para entregar el proyecto mañana "
            "con prioridad alta en categoría trabajo",
            ActionName.TASK_CREATE,
            {
                "title": "entregar el proyecto",
                "due": "manana",
                "priority": "alta",
                "category": "trabajo",
            },
        ),
        ("dime mis proyectos de Appa", ActionName.PROJECT_LIST, {}),
        (
            "crea un proyecto en Appa llamado Portafolio",
            ActionName.PROJECT_CREATE,
            {"name": "portafolio"},
        ),
        (
            "agenda una reunión de equipo mañana a las 9",
            ActionName.CALENDAR_CREATE,
            {"title": "de equipo", "start_at": "manana a las 9"},
        ),
        ("lista mi calendario de Appa", ActionName.CALENDAR_LIST, {}),
        (
            "guarda en mi inbox de Appa revisar esta idea",
            ActionName.INBOX_CAPTURE,
            {"text": "revisar esta idea"},
        ),
        ("lista mi inbox de Appa", ActionName.INBOX_LIST, {}),
        (
            "inicia una sesión de focus de 25 minutos para preparar la demo",
            ActionName.FOCUS_START,
            {"duration_minutes": 25, "task_title": "preparar la demo"},
        ),
        ("estado de mi sesión focus", ActionName.FOCUS_STATUS, {}),
        (
            "recuérdame enviar el reporte mañana a las 9",
            ActionName.REMINDER_CREATE,
            {"title": "enviar el reporte", "due": "manana a las 9", "recurrence": "none"},
        ),
        (
            "busca decoradores en mi biblioteca",
            ActionName.KNOWLEDGE_SEARCH,
            {"query": "decoradores"},
        ),
        (
            "indexa este adjunto",
            ActionName.KNOWLEDGE_ADD_ATTACHMENT,
            {"attachment_id": "latest"},
        ),
        (
            "resume lo que copié en mi portapapeles",
            ActionName.CLIPBOARD_ANALYZE,
            {"operation": "summarize"},
        ),
        (
            "ejecuta la receta diagnostico rapido",
            ActionName.SKILL_RUN,
            {"skill": "diagnostico_rapido", "parameters": {}},
        ),
        (
            "lee README.md del proyecto jarvis",
            ActionName.DEV_INSPECT,
            {"path": "readme.md", "workspace": "jarvis"},
        ),
        (
            "ejecuta las pruebas del proyecto jarvis",
            ActionName.DEV_TEST,
            {"workspace": "jarvis"},
        ),
        ("lista mis juegos", ActionName.GAME_LIST, {}),
        ("abre el juego Minecraft", ActionName.GAME_LAUNCH, {"game": "minecraft"}),
    ],
)
def test_new_natural_commands_are_typed_and_deterministic(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments


@pytest.mark.asyncio
async def test_suite_executes_tasks_reminders_knowledge_and_skills_with_fakes(
    tmp_path: Path,
) -> None:
    vision = NeverVision()
    suite = CapabilitySuite(settings(tmp_path), vision=vision)
    catalog = FakeCatalog()
    clipboard = NeverClipboard()

    created_task = await suite.execute(
        "owner",
        ActionName.TASK_CREATE,
        {"title": "Preparar demo"},
        clipboard=clipboard,
        catalog=catalog,
    )
    listed_task = await suite.execute(
        "owner",
        ActionName.TASK_LIST,
        {},
        clipboard=clipboard,
        catalog=catalog,
    )
    isolated_task = await suite.execute(
        "other",
        ActionName.TASK_LIST,
        {},
        clipboard=clipboard,
        catalog=catalog,
    )
    reminder = await suite.execute(
        "owner",
        ActionName.REMINDER_CREATE,
        {"title": "Probar Jarvis", "due": "en 20 minutos", "recurrence": "none"},
        clipboard=clipboard,
        catalog=catalog,
    )
    attachment = suite.attachments.save_bytes(
        "owner", "python.txt", "text/plain", b"Los decoradores envuelven funciones."
    )
    indexed = await suite.execute(
        "owner",
        ActionName.KNOWLEDGE_ADD_ATTACHMENT,
        {"attachment_id": attachment.attachment_id},
        clipboard=clipboard,
        catalog=catalog,
    )
    searched = await suite.execute(
        "owner",
        ActionName.KNOWLEDGE_SEARCH,
        {"query": "decoradores"},
        clipboard=clipboard,
        catalog=catalog,
    )
    isolated_search = await suite.execute(
        "other",
        ActionName.KNOWLEDGE_SEARCH,
        {"query": "decoradores"},
        clipboard=clipboard,
        catalog=catalog,
    )
    skill = await suite.execute(
        "owner",
        ActionName.SKILL_RUN,
        {"skill": "diagnostico_rapido", "parameters": {}},
        clipboard=clipboard,
        catalog=catalog,
    )

    assert created_task.success and listed_task.details["tasks"][0]["title"] == "Preparar demo"
    assert isolated_task.details["tasks"] == []
    assert reminder.success and reminder.details["reminder"]["title"] == "Probar Jarvis"
    assert indexed.success and searched.success
    assert isolated_search.success is False
    assert skill.success and len(catalog.workflows[0].steps) == 2
    assert vision.calls == 0


@pytest.mark.asyncio
async def test_suite_executes_real_appa_contract_without_network_or_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []
    task_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_payload
        payload = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, payload))
        if request.url.path == "/v1/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "service": "appa-jarvis-bridge",
                    "api_version": "v1",
                    "capabilities": [
                        "tasks.read",
                        "tasks.write",
                        "projects.read",
                        "projects.write",
                        "calendar.read",
                        "calendar.write",
                        "inbox.read",
                        "inbox.write",
                        "focus.read",
                        "focus.write",
                    ],
                },
            )
        if request.url.path == "/v1/projects" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "projects": [
                        {
                            "id": "project-1",
                            "name": "Jarvis",
                            "description": "",
                            "status": "active",
                            "target_date": None,
                            "created_at": "2026-08-10T12:00:00Z",
                            "updated_at": "2026-08-10T12:00:00Z",
                        }
                    ]
                },
            )
        if request.url.path == "/v1/projects":
            return httpx.Response(
                201,
                json={
                    "id": "project-2",
                    "name": payload["name"],
                    "description": payload["description"],
                    "status": "active",
                    "target_date": payload["target_date"],
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if request.url.path == "/v1/tasks" and request.method == "POST":
            task_payload = payload
            return httpx.Response(
                201,
                json={
                    "id": "task-1",
                    **payload,
                    "completed": False,
                    "source": "appa",
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if request.url.path == "/v1/tasks":
            return httpx.Response(200, json={"tasks": []})
        if request.url.path == "/v1/calendar/events" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "event-1",
                    **payload,
                    "source_type": "manual",
                    "source_id": None,
                    "completed": False,
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if request.url.path == "/v1/inbox" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "inbox-1",
                    "text": payload["text"],
                    "source": "jarvis",
                    "archived": False,
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if request.url.path == "/v1/focus" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "id": "focus-1",
                    "task_id": payload["task_id"],
                    "task_title": payload["task_title"],
                    "duration_minutes": payload["duration_minutes"],
                    "remaining_seconds": payload["duration_minutes"] * 60,
                    "status": "active",
                    "started_at": "2026-08-10T12:00:00Z",
                    "planned_end_at": "2026-08-10T12:25:00Z",
                    "completed": False,
                },
            )
        raise AssertionError(f"Ruta inesperada: {request.method} {request.url.path}")

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.capabilities.connectors.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    suite = CapabilitySuite(settings(tmp_path), vision=NeverVision())
    appa = AppaConnector("http://127.0.0.1:47651/v1", "a" * 40)
    suite.connectors = ConnectorRegistry(
        LocalTaskConnector(tmp_path / "isolated-tasks.sqlite3"),
        appa,
    )
    clipboard = NeverClipboard()
    catalog = FakeCatalog()

    task = await suite.execute(
        "owner",
        ActionName.TASK_CREATE,
        {
            "title": "Preparar demo",
            "due": "2099-01-02",
            "reminder_at": "2099-01-02T09:00:00-05:00",
            "priority": "alta",
            "category": "trabajo",
            "project_id": "Jarvis",
        },
        clipboard=clipboard,
        catalog=catalog,
    )
    project = await suite.execute(
        "owner",
        ActionName.PROJECT_CREATE,
        {"name": "Portafolio", "target_date": "2099-01-03"},
        clipboard=clipboard,
        catalog=catalog,
    )
    event = await suite.execute(
        "owner",
        ActionName.CALENDAR_CREATE,
        {"title": "Demo", "start_at": "2099-01-04T09:00:00-05:00"},
        clipboard=clipboard,
        catalog=catalog,
    )
    inbox = await suite.execute(
        "owner",
        ActionName.INBOX_CAPTURE,
        {"text": "Idea privada"},
        clipboard=clipboard,
        catalog=catalog,
    )
    focus = await suite.execute(
        "owner",
        ActionName.FOCUS_START,
        {"duration_minutes": 25, "task_title": "Preparar demo"},
        clipboard=clipboard,
        catalog=catalog,
    )

    assert all(result.success for result in (task, project, event, inbox, focus))
    assert task_payload["due"] == "2099-01-02"
    assert task_payload["reminder_at"] == "2099-01-02T14:00:00+00:00"
    assert task_payload["project_id"] == "project-1"
    assert task_payload["priority"] == "alta"
    assert task_payload["category"] == "trabajo"
    assert all(
        request[0] != "POST" or request[1].startswith("/v1/") for request in requests
    )
    await suite.close()


@pytest.mark.asyncio
async def test_system_status_uses_bounded_aggregate_monitor(tmp_path: Path) -> None:
    suite = CapabilitySuite(settings(tmp_path), vision=NeverVision())
    suite.system = FixedSystemMonitor()  # type: ignore[assignment]

    result = await suite.execute(
        "owner",
        ActionName.SYSTEM_STATUS,
        {},
        clipboard=NeverClipboard(),
        catalog=FakeCatalog(),
    )

    assert result.success is True
    assert "disco 61.0" in result.message
    assert result.details["memory_available_gb"] == 8.0


@pytest.mark.asyncio
async def test_suite_dev_and_game_execution_use_injected_fakes_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    suite = CapabilitySuite(settings(tmp_path), vision=NeverVision())
    developer = FakeDeveloper(tmp_path)
    suite.developer = developer  # type: ignore[assignment]
    monkeypatch.setattr(suite, "_game_library", lambda: FakeGames())
    catalog = FakeCatalog()
    clipboard = NeverClipboard()

    tests = await suite.execute(
        "owner",
        ActionName.DEV_TEST,
        {"workspace": "jarvis"},
        clipboard=clipboard,
        catalog=catalog,
    )
    game = await suite.execute(
        "owner",
        ActionName.GAME_LAUNCH,
        {"game": "Minecraft"},
        clipboard=clipboard,
        catalog=catalog,
    )

    assert tests.success and developer.calls == 1
    assert game.success
    assert catalog.apps.launches == [("steam://rungameid/123", "Minecraft")]


@pytest.mark.asyncio
async def test_system_alerts_reach_each_session_once_without_crossing_private_items(
    tmp_path: Path,
) -> None:
    suite = CapabilitySuite(settings(tmp_path), vision=NeverVision())
    assert suite.notifications("owner", consume=True) == []
    assert suite.notifications("other", consume=True) == []
    await suite._notify("owner", {"event": "reminder", "title": "Privado"})
    await suite._notify("system", {"event": "system-alert", "message": "Memoria alta"})

    owner = suite.notifications("owner", consume=True)
    other = suite.notifications("other", consume=True)

    assert [item["event"] for item in owner] == ["reminder", "system-alert"]
    assert [item["event"] for item in other] == ["system-alert"]
    assert suite.notifications("owner", consume=True) == []
    assert suite.notifications("other", consume=True) == []
    assert all("_sequence" not in item for item in owner + other)


@pytest.mark.asyncio
async def test_new_session_does_not_replay_historical_system_alerts(tmp_path: Path) -> None:
    suite = CapabilitySuite(settings(tmp_path), vision=NeverVision())
    await suite._notify("system", {"event": "system-alert", "message": "Memoria alta"})

    assert suite.notifications("new-tab", consume=True) == []

    await suite._notify("system", {"event": "system-alert", "message": "Memoria normal"})
    assert [item["message"] for item in suite.notifications("new-tab", consume=True)] == [
        "Memoria normal"
    ]
