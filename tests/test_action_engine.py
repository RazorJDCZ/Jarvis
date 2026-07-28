from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import (
    ActionName,
    ActionPlan,
    ActionRisk,
    ActionSource,
    ActionStatus,
    ExecutionResult,
    PreparedAction,
    PreparedWorkflow,
)
from jarvis.actions.windows import InstalledApp
from jarvis.config import Settings


class FakeBrowser:
    async def status(self) -> ExecutionResult:
        return ExecutionResult(True, "browser ok")


class RecordingCatalog:
    def __init__(self, tmp_path: Path, result: ExecutionResult | None = None) -> None:
        self.real = ActionCatalog(tmp_path, "https://example.com/?q={query}")
        self.action_names = self.real.action_names
        self.browser = FakeBrowser()
        self.result = result or ExecutionResult(True, "Acción verificada", {"verified": True})
        self.executed = []
        self.dialog_choices: list[tuple[int, int, str]] = []
        self.dialog_is_available = True

    def prepare(self, plan: ActionPlan):
        return self.real.prepare(plan)

    async def execute(self, action):
        self.executed.append(action)
        return self.result

    async def choose_dialog_option(self, parent_handle, dialog_handle, choice):
        self.dialog_choices.append((parent_handle, dialog_handle, choice))
        return ExecutionResult(True, f"Elegí {choice}", {"choice": choice, "verified": True})

    async def dialog_available(self, _parent_handle, _dialog_handle):
        return self.dialog_is_available

    async def close(self) -> None:
        return None


class ExplodingCatalog(RecordingCatalog):
    async def execute(self, action):
        self.executed.append(action)
        raise RuntimeError("detalle interno potencialmente sensible")


class ExplodingPrepareCatalog(RecordingCatalog):
    def prepare(self, plan: ActionPlan):
        raise OSError("ruta interna potencialmente sensible")


class FixedPlanner:
    def __init__(self, plan: ActionPlan | None) -> None:
        self.planned_action = plan
        self.calls: list[str] = []

    async def plan(self, text: str) -> ActionPlan | None:
        self.calls.append(text)
        return self.planned_action


def build_engine(
    tmp_path: Path,
    catalog: RecordingCatalog | None = None,
    planner: FixedPlanner | None = None,
    **settings: object,
) -> tuple[ActionEngine, RecordingCatalog]:
    action_catalog = catalog or RecordingCatalog(tmp_path)
    config = Settings(project_root=tmp_path, **settings)
    return (
        ActionEngine(config, catalog=action_catalog, planner=planner),
        action_catalog,
    )


@pytest.mark.asyncio
async def test_low_risk_exact_action_executes_immediately(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    result = await engine.try_handle("session", "abre la calculadora")

    assert result.status is ActionStatus.COMPLETED
    assert result.name is ActionName.APP_OPEN
    assert result.details["verified"] is True
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_explicit_browser_reaches_catalog_as_typed_action(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    result = await engine.try_handle("session", "abre YouTube en Google Chrome")

    assert result.status is ActionStatus.COMPLETED
    assert action_catalog.executed[0].name is ActionName.BROWSER_OPEN
    assert action_catalog.executed[0].arguments == {
        "url": "https://www.youtube.com/",
        "browser": "chrome",
    }


@pytest.mark.asyncio
async def test_discovered_application_requires_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, action_catalog = build_engine(tmp_path)
    monkeypatch.setattr(
        action_catalog.real.apps,
        "find_installed_apps",
        lambda _name: (InstalledApp("Discord", "Discord.App"),),
    )

    pending = await engine.try_handle("session", "abre Discord")
    completed = await engine.decide("session", pending.action_id, True)

    assert pending.status is ActionStatus.PENDING
    assert pending.description == "Abrir la aplicación instalada Discord"
    assert completed.status is ActionStatus.COMPLETED
    assert action_catalog.executed[0].arguments["app_id"] == "Discord.App"


@pytest.mark.asyncio
async def test_medium_risk_action_waits_for_matching_confirmation(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    pending = await engine.try_handle("session", "haz clic en Aceptar")
    wrong = await engine.decide("other", pending.action_id, True)
    completed = await engine.decide("session", pending.action_id, True)

    assert pending.status is ActionStatus.PENDING
    assert pending.requires_confirmation is True
    assert wrong.status is ActionStatus.REJECTED
    assert completed.status is ActionStatus.COMPLETED
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_pending_action_can_be_confirmed_or_cancelled_by_voice(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)
    await engine.try_handle("a", "cierra la ventana de Paint")
    cancelled = await engine.try_handle("a", "no lo hagas")
    await engine.try_handle("b", "cierra la ventana de Paint")
    confirmed = await engine.try_handle("b", "sí, hazlo")

    assert cancelled.status is ActionStatus.CANCELLED
    assert confirmed.status is ActionStatus.COMPLETED
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_new_dialog_requires_an_explicit_option_and_accepts_voice_choice(
    tmp_path: Path,
) -> None:
    action_catalog = RecordingCatalog(
        tmp_path,
        ExecutionResult(
            True,
            "Solicitud de cierre enviada.",
            {
                "dialog_confirmation_required": True,
                "dialog": {
                    "parent_handle": 100,
                    "dialog_handle": 200,
                    "title": "Bloc de notas",
                    "message": "¿Quieres guardar los cambios?",
                    "options": ["Guardar", "No guardar", "Cancelar"],
                },
            },
        ),
    )
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    close_pending = await engine.try_handle("a", "cierra la ventana de Bloc de notas")

    dialog_pending = await engine.decide("a", close_pending.action_id, True)
    still_waiting = await engine.try_handle("a", "haz lo que creas mejor")
    completed = await engine.try_handle("a", "no guardes")

    assert dialog_pending.status is ActionStatus.PENDING
    assert dialog_pending.name is ActionName.DIALOG_CHOOSE
    assert dialog_pending.details["dialog_options"] == ["Guardar", "No guardar", "Cancelar"]
    assert still_waiting.status is ActionStatus.PENDING
    assert action_catalog.dialog_choices == [(100, 200, "No guardar")]
    assert completed.status is ActionStatus.COMPLETED
    audit_text = (tmp_path / ".data/action-audit.jsonl").read_text(encoding="utf-8")
    assert "¿Quieres guardar" not in audit_text
    assert '"options":"<redacted>"' in audit_text


@pytest.mark.asyncio
async def test_dialog_api_approval_never_guesses_among_multiple_options(tmp_path: Path) -> None:
    action_catalog = RecordingCatalog(tmp_path)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    waiting = engine._request_dialog(
        "a",
        {
            "parent_handle": 1,
            "dialog_handle": 2,
            "title": "Permiso",
            "message": "¿Permitir acceso?",
            "options": ["Permitir", "Denegar"],
        },
    )

    ambiguous = await engine.decide("a", waiting.action_id, True)
    explicit = await engine.decide("a", waiting.action_id, None, "Permitir")

    assert ambiguous.status is ActionStatus.PENDING
    assert explicit.status is ActionStatus.COMPLETED
    assert action_catalog.dialog_choices == [(1, 2, "Permitir")]


@pytest.mark.asyncio
async def test_manually_closed_dialog_does_not_block_future_commands(tmp_path: Path) -> None:
    action_catalog = RecordingCatalog(tmp_path)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    engine._request_dialog(
        "a",
        {
            "parent_handle": 1,
            "dialog_handle": 2,
            "title": "Permiso",
            "message": "¿Permitir acceso?",
            "options": ["Permitir", "Denegar"],
        },
    )
    action_catalog.dialog_is_available = False

    result = await engine.try_handle("a", "abre la calculadora")

    assert result.status is ActionStatus.COMPLETED
    assert "a" not in engine._dialogs


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", ["sí", "claro que sí", "dale", "autorizo"])
async def test_natural_voice_confirmation_variants(
    tmp_path: Path,
    confirmation: str,
) -> None:
    engine, action_catalog = build_engine(tmp_path)
    await engine.try_handle("a", "haz clic en Aceptar")

    result = await engine.try_handle("a", confirmation)

    assert result.status is ActionStatus.COMPLETED
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_confirmation_word_without_pending_action_remains_conversational(
    tmp_path: Path,
) -> None:
    engine, _ = build_engine(tmp_path)

    assert await engine.try_handle("a", "sí") is None


@pytest.mark.asyncio
async def test_dangerous_request_is_blocked_before_planner(tmp_path: Path) -> None:
    planner = FixedPlanner(ActionPlan(ActionName.APP_OPEN, {"app": "calculator"}))
    engine, action_catalog = build_engine(tmp_path, planner=planner)

    result = await engine.try_handle("a", "abre powershell")

    assert result.status is ActionStatus.BLOCKED
    assert planner.calls == []
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_unknown_application_is_blocked(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    result = await engine.try_handle("a", "abre una-app-que-no-existe")

    assert result.status is ActionStatus.BLOCKED
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_model_planned_mutation_requires_confirmation(tmp_path: Path) -> None:
    plan = ActionPlan(
        ActionName.VOLUME_SET,
        {"level": 30},
        source=ActionSource.LOCAL_MODEL,
        confidence=0.95,
    )
    planner = FixedPlanner(plan)
    engine, action_catalog = build_engine(tmp_path, planner=planner)

    pending = await engine.try_handle("a", "configura el sonido a treinta")

    assert pending.status is ActionStatus.PENDING
    assert planner.calls == ["configura el sonido a treinta"]
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_conversation_is_not_sent_to_action_planner(tmp_path: Path) -> None:
    planner = FixedPlanner(ActionPlan(ActionName.APP_OPEN, {"app": "calculator"}))
    engine, _ = build_engine(tmp_path, planner=planner)

    result = await engine.try_handle("a", "explícame qué es una calculadora")

    assert result is None
    assert planner.calls == []


@pytest.mark.asyncio
async def test_disabled_engine_never_executes(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path, safe_actions_enabled=False)

    result = await engine.try_handle("a", "abre la calculadora")

    assert result.status is ActionStatus.BLOCKED
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_execution_failure_is_reported_honestly(tmp_path: Path) -> None:
    action_catalog = RecordingCatalog(tmp_path, ExecutionResult(False, "No abrió"))
    engine, _ = build_engine(tmp_path, catalog=action_catalog)

    result = await engine.try_handle("a", "abre la calculadora")

    assert result.status is ActionStatus.FAILED
    assert result.message == "No abrió"


@pytest.mark.asyncio
async def test_unexpected_controller_error_is_contained(tmp_path: Path) -> None:
    action_catalog = ExplodingCatalog(tmp_path)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)

    result = await engine.try_handle("a", "abre la calculadora")

    assert result.status is ActionStatus.FAILED
    assert result.message == "La acción falló de forma controlada: RuntimeError."
    assert "sensible" not in result.message


@pytest.mark.asyncio
async def test_unexpected_preparation_error_is_contained(tmp_path: Path) -> None:
    action_catalog = ExplodingPrepareCatalog(tmp_path)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)

    result = await engine.try_handle("a", "abre la calculadora")

    assert result.status is ActionStatus.FAILED
    assert result.message == "No pude preparar la acción de forma segura: OSError."
    assert "sensible" not in result.message


@pytest.mark.asyncio
async def test_audit_redacts_typed_content(tmp_path: Path) -> None:
    engine, _ = build_engine(tmp_path)
    pending = await engine.try_handle("a", 'escribe "secreto local"')
    await engine.decide("a", pending.action_id, True)

    entries = engine.recent_audit(10)

    assert entries[-1]["arguments"]["text"] == "<redacted>"
    assert "secreto local" not in (tmp_path / ".data/action-audit.jsonl").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_audit_redacts_visible_window_content(tmp_path: Path) -> None:
    engine, _ = build_engine(tmp_path)

    result = await engine.try_handle("a", "lista las ventanas")
    entries = engine.recent_audit(10)

    assert result.status is ActionStatus.COMPLETED
    assert entries[-1]["message"] == "<redacted>"


@pytest.mark.asyncio
async def test_expired_confirmation_cannot_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr("jarvis.actions.engine.time.monotonic", lambda: now["value"])
    engine, action_catalog = build_engine(tmp_path, action_confirmation_seconds=15)
    pending = await engine.try_handle("a", "cierra la ventana de Paint")

    now["value"] = 116.0
    result = await engine.decide("a", pending.action_id, True)

    assert result.status is ActionStatus.REJECTED
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_new_pending_action_invalidates_previous_one(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)
    first = await engine.try_handle("a", "cierra la ventana de Paint")
    second = await engine.try_handle("a", "cierra la ventana de Notepad")

    stale = await engine.decide("a", first.action_id, True)
    current = await engine.decide("a", second.action_id, True)

    assert stale.status is ActionStatus.REJECTED
    assert current.status is ActionStatus.COMPLETED
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_low_risk_compound_request_executes_as_one_workflow(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    result = await engine.try_handle("a", "abre la calculadora y maximiza la ventana")

    assert result.status is ActionStatus.COMPLETED
    assert result.name is ActionName.WORKFLOW_RUN
    assert len(action_catalog.executed) == 1
    workflow = action_catalog.executed[0]
    assert isinstance(workflow, PreparedWorkflow)
    assert tuple(step.name for step in workflow.steps) == (
        ActionName.APP_OPEN,
        ActionName.WINDOW_MAXIMIZE,
    )


@pytest.mark.asyncio
async def test_sensitive_compound_request_has_one_confirmation_and_nested_redaction(
    tmp_path: Path,
) -> None:
    engine, action_catalog = build_engine(tmp_path)

    pending = await engine.try_handle(
        "a",
        'abre el bloc de notas y escribe "dato privado y local"',
    )
    completed = await engine.decide("a", pending.action_id, True)

    assert pending.status is ActionStatus.PENDING
    assert pending.name is ActionName.WORKFLOW_RUN
    assert completed.status is ActionStatus.COMPLETED
    assert isinstance(action_catalog.executed[0], PreparedWorkflow)
    audit_text = (tmp_path / ".data/action-audit.jsonl").read_text(encoding="utf-8")
    assert "dato privado" not in audit_text
    assert '"text":"<redacted>"' in audit_text


@pytest.mark.asyncio
async def test_visual_reference_is_session_bound_and_relocated(tmp_path: Path) -> None:
    result = ExecutionResult(
        True,
        "Elemento localizado",
        {"target": "botón aceptar", "x": 100, "y": 200},
    )
    action_catalog = RecordingCatalog(tmp_path, result)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    located = await engine.try_handle("owner", "encuentra visualmente el botón aceptar")
    await engine.decide("owner", located.action_id, True)

    owner = await engine.try_handle("owner", "haz clic ahí")
    other = await engine.try_handle("other", "haz clic ahí")

    assert owner.status is ActionStatus.PENDING
    assert owner.risk is ActionRisk.HIGH
    assert engine._pending["owner"].action.arguments["target"] == "botón aceptar"
    assert other.status is ActionStatus.REJECTED


@pytest.mark.asyncio
async def test_visual_followup_reuses_monitor_but_requests_a_fresh_analysis(
    tmp_path: Path,
) -> None:
    visual_result = ExecutionResult(
        True,
        "En Monitor 2 hay un mensaje de error.",
        {
            "summary": "Hay un mensaje de error.",
            "interactive_elements": ["Aceptar"],
            "monitor": "2",
            "monitor_label": "Monitor 2",
            "ephemeral_capture": True,
        },
    )
    action_catalog = RecordingCatalog(tmp_path, visual_result)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    first = await engine.try_handle("owner", "qué ves en el monitor 2")
    await engine.decide("owner", first.action_id, True)

    followup = await engine.try_handle("owner", "¿qué dice ese error?")

    assert followup.status is ActionStatus.PENDING
    prepared = engine._pending["owner"].action
    assert prepared.name is ActionName.SCREEN_ASK
    assert prepared.arguments["monitor"] == "2"
    assert prepared.arguments["question"] == "¿qué dice ese error?"
    assert len(action_catalog.executed) == 1


@pytest.mark.asyncio
async def test_visual_context_is_isolated_by_session_and_reset(tmp_path: Path) -> None:
    visual_result = ExecutionResult(
        True,
        "Pantalla observada.",
        {
            "summary": "Una ventana.",
            "monitor": "2",
            "monitor_label": "Monitor 2",
        },
    )
    action_catalog = RecordingCatalog(tmp_path, visual_result)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    first = await engine.try_handle("owner", "describe el monitor 2")
    await engine.decide("owner", first.action_id, True)

    other = await engine.try_handle("other", "qué dice ese mensaje")
    engine.reset("owner")
    reset_owner = await engine.try_handle("owner", "qué dice ese mensaje")

    assert other is None
    assert reset_owner is None


@pytest.mark.asyncio
async def test_known_visual_control_uses_monitor_specific_safe_click(tmp_path: Path) -> None:
    visual_result = ExecutionResult(
        True,
        "Formulario visible.",
        {
            "summary": "Formulario visible.",
            "interactive_elements": ["Aceptar"],
            "monitor": "2",
            "monitor_label": "Monitor 2",
        },
    )
    action_catalog = RecordingCatalog(tmp_path, visual_result)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    first = await engine.try_handle("owner", "describe el monitor 2")
    await engine.decide("owner", first.action_id, True)

    click = await engine.try_handle("owner", "haz clic en Aceptar")

    assert click.status is ActionStatus.PENDING
    assert click.risk is ActionRisk.HIGH
    prepared = engine._pending["owner"].action
    assert prepared.name is ActionName.SCREEN_CLICK
    assert prepared.arguments == {"target": "aceptar", "monitor": "2"}


@pytest.mark.asyncio
async def test_expired_visual_context_is_not_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr("jarvis.actions.engine.time.monotonic", lambda: now["value"])
    visual_result = ExecutionResult(
        True,
        "Pantalla observada.",
        {"summary": "Un error.", "monitor": "2", "monitor_label": "Monitor 2"},
    )
    action_catalog = RecordingCatalog(tmp_path, visual_result)
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    first = await engine.try_handle("owner", "describe el monitor 2")
    await engine.decide("owner", first.action_id, True)

    now["value"] = 401.0
    followup = await engine.try_handle("owner", "qué dice ese error")

    assert followup is None


@pytest.mark.asyncio
async def test_catalog_workflow_stops_after_first_failed_step(tmp_path: Path) -> None:
    action_catalog = ActionCatalog(tmp_path, "https://example.com/?q={query}")
    calls: list[str] = []
    action_catalog.apps.open = lambda *_args: ExecutionResult(False, "No abrió")

    def audio_level() -> ExecutionResult:
        calls.append("audio")
        return ExecutionResult(True, "Volumen leído")

    action_catalog.audio.get_level = audio_level
    workflow = PreparedWorkflow(
        steps=(
            PreparedAction(
                ActionName.APP_OPEN,
                {"app": "calculator"},
                ActionRisk.LOW,
                "Abrir calculadora",
                ActionSource.DETERMINISTIC,
            ),
            PreparedAction(
                ActionName.VOLUME_GET,
                {},
                ActionRisk.LOW,
                "Leer volumen",
                ActionSource.DETERMINISTIC,
            ),
        ),
        risk=ActionRisk.LOW,
        description="Flujo de prueba",
        source=ActionSource.DETERMINISTIC,
    )

    result = await action_catalog.execute(workflow)

    assert result.success is False
    assert result.details["completed_steps"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_visual_pixel_click_requires_two_separate_confirmations(tmp_path: Path) -> None:
    action_catalog = RecordingCatalog(
        tmp_path,
        ExecutionResult(
            True,
            "Cursor movido al objetivo estimado.",
            {
                "x": 400,
                "y": 300,
                "element": "Botón seguro",
                "pixel_confirmation_required": True,
            },
        ),
    )
    engine, _ = build_engine(tmp_path, catalog=action_catalog)
    first = await engine.try_handle("a", "haz clic visualmente en el botón seguro")

    second = await engine.decide("a", first.action_id, True)
    completed = await engine.decide("a", second.action_id, True)

    assert first.status is ActionStatus.PENDING
    assert second.status is ActionStatus.PENDING
    assert second.name is ActionName.POINTER_CLICK
    assert second.details["cursor_moved"] is True
    assert completed.status is ActionStatus.COMPLETED
    assert len(action_catalog.executed) == 2


@pytest.mark.asyncio
async def test_visual_click_is_rejected_inside_compound_workflow(tmp_path: Path) -> None:
    engine, action_catalog = build_engine(tmp_path)

    result = await engine.try_handle(
        "a",
        "abre la calculadora y haz clic visualmente en aceptar",
    )

    assert result.status is ActionStatus.BLOCKED
    assert "por separado" in result.message
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_fuzzy_clause_and_exact_clause_form_complete_workflow(tmp_path: Path) -> None:
    planner = FixedPlanner(
        ActionPlan(
            ActionName.APP_OPEN,
            {"app": "notepad"},
            source=ActionSource.LOCAL_MODEL,
            confidence=0.94,
        )
    )
    engine, action_catalog = build_engine(tmp_path, planner=planner)

    pending = await engine.try_handle(
        "a",
        'quiero tener el bloc de notas abierto y después escribe "hola desde jarvis"',
    )

    assert pending.status is ActionStatus.PENDING
    assert pending.name is ActionName.WORKFLOW_RUN
    assert planner.calls == ["quiero tener el bloc de notas abierto"]
    workflow = engine._pending["a"].action
    assert tuple(step.name for step in workflow.steps) == (
        ActionName.APP_OPEN,
        ActionName.UI_TYPE,
    )
    assert action_catalog.executed == []


@pytest.mark.asyncio
async def test_reset_removes_pending_confirmation(tmp_path: Path) -> None:
    engine, _ = build_engine(tmp_path)
    pending = await engine.try_handle("a", "cierra la ventana")

    engine.reset("a")
    result = await engine.decide("a", pending.action_id, True)

    assert result.status is ActionStatus.REJECTED
