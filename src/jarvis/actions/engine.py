from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from uuid import uuid4

from jarvis.actions.audit import ActionAuditLog
from jarvis.actions.catalog import ActionCatalog, ActionSecurityError
from jarvis.actions.models import (
    ActionName,
    ActionOutcome,
    ActionPlan,
    ActionRisk,
    ActionSource,
    ActionStatus,
    ActionWorkflowPlan,
    BlockedIntent,
    ExecutionResult,
    PendingAction,
    PendingDialog,
    PreparedAction,
    PreparedWorkflow,
)
from jarvis.actions.parser import DeterministicActionParser, normalize_request
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


@dataclass(frozen=True, slots=True)
class VisualSessionContext:
    monitor: str
    monitor_label: str
    summary: str
    interactive_elements: tuple[str, ...]
    last_target: str | None
    created_at: float


class ActionEngine:
    _VISUAL_ACTIONS = frozenset(
        {
            ActionName.SCREEN_DESCRIBE,
            ActionName.SCREEN_ASK,
            ActionName.SCREEN_FIND,
            ActionName.SCREEN_CLICK,
        }
    )
    _VISUAL_CONTEXT_SECONDS = 300
    _CONFIRMATIONS = frozenset(
        {
            "adelante",
            "autorizo",
            "claro que si",
            "confirma",
            "confirmado",
            "confirmo",
            "dale",
            "hazlo",
            "procede",
            "si",
            "si confirma",
            "si hazlo",
            "si por favor",
        }
    )
    _CANCELLATIONS = frozenset(
        {
            "cancela",
            "cancelado",
            "cancelar",
            "detente",
            "mejor no",
            "no cancelalo",
            "no gracias",
            "no lo hagas",
            "olvidalo",
            "rechaza",
        }
    )

    def __init__(
        self,
        settings: Settings,
        catalog: ActionCatalog | None = None,
        parser: DeterministicActionParser | None = None,
        planner: LocalActionPlanner | None = None,
        audit: ActionAuditLog | None = None,
    ) -> None:
        self.settings = settings
        self.catalog = catalog or ActionCatalog(
            settings.data_dir,
            settings.browser_search_url,
            settings,
        )
        self.parser = parser or DeterministicActionParser()
        self.planner = planner or LocalActionPlanner(settings, self.catalog.action_names)
        self.audit = audit or ActionAuditLog(settings.data_dir / "action-audit.jsonl")
        self._pending: OrderedDict[str, PendingAction] = OrderedDict()
        self._dialogs: OrderedDict[str, PendingDialog] = OrderedDict()
        self._visual_contexts: OrderedDict[str, VisualSessionContext] = OrderedDict()
        self._execution_lock = asyncio.Lock()

    async def status(self) -> ProviderStatus:
        browser = await self.catalog.browser.status()
        enabled = self.settings.safe_actions_enabled
        return ProviderStatus(
            available=enabled,
            name="Motor de acciones / Windows",
            detail=(
                f"Lista blanca activa; {len(self.catalog.action_names)} acciones; {browser.message}"
                if enabled
                else "El motor está desactivado mediante configuración"
            ),
        )

    async def vision_status(self) -> ProviderStatus:
        vision_controller = getattr(self.catalog, "vision", None)
        if vision_controller is None:
            return ProviderStatus(
                available=False,
                name="Visión local",
                detail="La percepción visual no está configurada",
            )
        result = await vision_controller.status()
        return ProviderStatus(
            available=result.success and self.settings.safe_actions_enabled,
            name=f"Visión local / {self.settings.ollama_model}",
            detail=result.message,
        )

    def _prune_pending(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired = [
            session for session, pending in self._pending.items() if current > pending.expires_at
        ]
        for session in expired:
            self._pending.pop(session, None)
        expired_contexts = [
            session
            for session, context in self._visual_contexts.items()
            if current - context.created_at > self._VISUAL_CONTEXT_SECONDS
        ]
        for session in expired_contexts:
            self._visual_contexts.pop(session, None)

    @staticmethod
    def _blocked(message: str) -> ActionOutcome:
        return ActionOutcome(status=ActionStatus.BLOCKED, message=message, risk=ActionRisk.BLOCKED)

    async def try_handle(self, session_id: str, text: str) -> ActionOutcome | None:
        self._prune_pending()
        command = normalize_request(text)
        decision = re.sub(r"[,;.!?]+", " ", command)
        decision = re.sub(r"\s+", " ", decision).strip()
        dialog = self._dialogs.get(session_id)
        if dialog is not None and not await self.catalog.dialog_available(
            dialog.parent_handle,
            dialog.dialog_handle,
        ):
            self._dialogs.pop(session_id, None)
            dialog = None
        if dialog is not None:
            choice = self._match_dialog_choice(decision, dialog.options)
            if choice is not None:
                return await self._decide_dialog(session_id, dialog.action_id, choice)
            return self._dialog_outcome(
                dialog,
                prefix="El diálogo sigue esperando una decisión.",
            )
        pending = self._pending.get(session_id)
        if decision in self._CONFIRMATIONS:
            if pending is None:
                return None
            return await self.decide(session_id, pending.action_id, approve=True)
        if decision in self._CANCELLATIONS:
            if pending is None:
                return None
            return await self.decide(session_id, pending.action_id, approve=False)

        parsed = self.parser.parse(text)
        if isinstance(parsed, BlockedIntent):
            return self._blocked(parsed.reason)
        parsed = await self._expand_explicit_workflow(text, parsed)
        if isinstance(parsed, BlockedIntent):
            return self._blocked(parsed.reason)
        if parsed is None and self.parser.looks_action_like(text):
            parsed = await self.planner.plan(text)
        parsed = self._apply_visual_context(session_id, text, parsed)
        if parsed is None:
            return None
        if not self.settings.safe_actions_enabled:
            return self._blocked("El motor de acciones está desactivado en la configuración.")
        resolved = self._resolve_visual_reference(session_id, parsed)
        if isinstance(resolved, ActionOutcome):
            return resolved
        try:
            prepared = self._prepare(resolved)
        except ActionSecurityError as exc:
            return self._blocked(str(exc))
        except Exception as exc:
            return ActionOutcome(
                status=ActionStatus.FAILED,
                message=f"No pude preparar la acción de forma segura: {type(exc).__name__}.",
            )

        if prepared.risk in {ActionRisk.MEDIUM, ActionRisk.HIGH}:
            return self._request_confirmation(session_id, prepared)
        return await self._execute(session_id, prepared)

    async def _expand_explicit_workflow(
        self,
        text: str,
        current: ActionPlan | ActionWorkflowPlan | None,
    ) -> ActionPlan | ActionWorkflowPlan | BlockedIntent | None:
        if isinstance(current, ActionWorkflowPlan):
            return current
        parts = self.parser.workflow_parts(text)
        if not 2 <= len(parts) <= 3:
            return current
        steps: list[ActionPlan] = []
        for part in parts:
            candidate = self.parser.parse(part)
            if isinstance(candidate, BlockedIntent):
                return candidate
            if candidate is None and self.parser.looks_action_like(part):
                candidate = await self.planner.plan(part)
            if isinstance(candidate, ActionWorkflowPlan):
                steps.extend(candidate.steps)
            elif isinstance(candidate, ActionPlan):
                steps.append(candidate)
            else:
                return current
        if not 2 <= len(steps) <= 3:
            return current
        source = (
            ActionSource.LOCAL_MODEL
            if any(step.source is ActionSource.LOCAL_MODEL for step in steps)
            else ActionSource.DETERMINISTIC
        )
        return ActionWorkflowPlan(
            steps=tuple(steps),
            source=source,
            confidence=min(step.confidence for step in steps),
        )

    @staticmethod
    def _looks_like_visual_followup(command: str) -> bool:
        explicit_reference = re.search(
            r"\b(?:ahi|eso|ese|esa|este|esta)\b|"
            r"\b(?:pantalla|monitor|error|mensaje|ventana|boton|icono|imagen)\b|"
            r"\blo que (?:ves|aparece|mencionaste)\b",
            command,
        )
        question_or_instruction = re.match(
            r"^(?:que|cual|donde|como|por que|puedes leer|lee|dime|explica|"
            r"encuentra|localiza|haz clic|pulsa|presiona)\b",
            command,
        )
        return (
            explicit_reference is not None
            and question_or_instruction is not None
            and len(command.split()) <= 20
        )

    def _apply_visual_context(
        self,
        session_id: str,
        text: str,
        plan: ActionPlan | ActionWorkflowPlan | None,
    ) -> ActionPlan | ActionWorkflowPlan | None:
        context = self._visual_contexts.get(session_id)
        if plan is None:
            command = normalize_request(text)
            if context is None or not self._looks_like_visual_followup(command):
                return None
            return ActionPlan(
                name=ActionName.SCREEN_ASK,
                arguments={"question": text.strip(), "monitor": context.monitor},
            )

        def enrich(step: ActionPlan) -> ActionPlan:
            arguments = dict(step.arguments)
            if step.name in self._VISUAL_ACTIONS:
                if "monitor" not in arguments and context is not None:
                    arguments["monitor"] = context.monitor
                return replace(step, arguments=arguments)
            if (
                context is not None
                and step.name in {ActionName.BROWSER_CLICK, ActionName.UI_CLICK}
                and isinstance(arguments.get("target"), str)
            ):
                target = normalize_request(arguments["target"])
                known_elements = {
                    normalize_request(element) for element in context.interactive_elements
                }
                if target in known_elements:
                    return ActionPlan(
                        name=ActionName.SCREEN_CLICK,
                        arguments={
                            "target": arguments["target"],
                            "monitor": context.monitor,
                        },
                        source=step.source,
                        confidence=step.confidence,
                    )
            return step

        if isinstance(plan, ActionWorkflowPlan):
            return replace(plan, steps=tuple(enrich(step) for step in plan.steps))
        return enrich(plan)

    def _resolve_visual_reference(
        self,
        session_id: str,
        plan: ActionPlan | ActionWorkflowPlan,
    ) -> ActionPlan | ActionWorkflowPlan | ActionOutcome:
        def resolve_step(step: ActionPlan) -> ActionPlan | None:
            if (
                step.name is ActionName.SCREEN_CLICK
                and step.arguments.get("target") == self.parser.LAST_VISUAL_TARGET
            ):
                context = self._visual_contexts.get(session_id)
                if context is None or context.last_target is None:
                    return None
                arguments = dict(step.arguments)
                arguments["target"] = context.last_target
                arguments.setdefault("monitor", context.monitor)
                return ActionPlan(
                    name=step.name,
                    arguments=arguments,
                    source=step.source,
                    confidence=step.confidence,
                )
            return step

        if isinstance(plan, ActionWorkflowPlan):
            steps = tuple(resolve_step(step) for step in plan.steps)
            if any(step is None for step in steps):
                return ActionOutcome(
                    status=ActionStatus.REJECTED,
                    message=(
                        "No tengo un elemento visual reciente al que se refiera ‘ahí’. "
                        "Primero pídeme que lo localice."
                    ),
                )
            return ActionWorkflowPlan(
                steps=tuple(step for step in steps if step is not None),
                source=plan.source,
                confidence=plan.confidence,
            )
        resolved = resolve_step(plan)
        if resolved is None:
            return ActionOutcome(
                status=ActionStatus.REJECTED,
                message=(
                    "No tengo un elemento visual reciente al que se refiera ‘ahí’. "
                    "Primero pídeme que lo localice."
                ),
            )
        return resolved

    def _prepare(self, plan: ActionPlan | ActionWorkflowPlan) -> PreparedAction | PreparedWorkflow:
        if isinstance(plan, ActionPlan):
            return self.catalog.prepare(plan)
        if not 2 <= len(plan.steps) <= 3:
            raise ActionSecurityError("Un flujo puede contener entre dos y tres acciones.")
        steps = tuple(self.catalog.prepare(step) for step in plan.steps)
        if any(step.name is ActionName.SCREEN_CLICK for step in steps):
            raise ActionSecurityError(
                "El clic visual debe ejecutarse por separado porque requiere dos confirmaciones."
            )
        risk_rank = {ActionRisk.LOW: 1, ActionRisk.MEDIUM: 2, ActionRisk.HIGH: 3}
        risk = max((step.risk for step in steps), key=risk_rank.__getitem__)
        description = "Ejecutar en orden: " + "; luego ".join(step.description for step in steps)
        return PreparedWorkflow(
            steps=steps,
            risk=risk,
            description=description,
            source=plan.source,
        )

    def _request_confirmation(
        self,
        session_id: str,
        action: PreparedAction | PreparedWorkflow,
    ) -> ActionOutcome:
        now = time.monotonic()
        action_id = uuid4().hex
        pending = PendingAction(
            action_id=action_id,
            session_id=session_id,
            action=action,
            created_at=now,
            expires_at=now + max(15, self.settings.action_confirmation_seconds),
        )
        self._pending[session_id] = pending
        self._pending.move_to_end(session_id)
        while len(self._pending) > max(1, self.settings.max_sessions):
            self._pending.popitem(last=False)
        risk_label = "alto" if action.risk is ActionRisk.HIGH else "medio"
        outcome = ActionOutcome(
            status=ActionStatus.PENDING,
            message=(
                f"Necesito tu confirmación para: {action.description}. Riesgo {risk_label}. "
                "Di confirma o cancela, o usa los botones de la interfaz."
            ),
            action_id=action_id,
            name=action.name,
            risk=action.risk,
            description=action.description,
            requires_confirmation=True,
        )
        self.audit.record(session_id, action, outcome)
        return outcome

    @staticmethod
    def _match_dialog_choice(text: str, options: tuple[str, ...]) -> str | None:
        command = re.sub(
            r"^(?:elige|selecciona|pulsa|presiona|haz clic en|quiero|escoge) "
            r"(?:la opcion )?",
            "",
            text,
        ).strip()
        normalized_options = sorted(
            ((normalize_request(option), option) for option in options),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        aliases = {
            "guardar": {"guarda", "guardar", "si guarda", "quiero guardar"},
            "save": {"save", "guardar"},
            "no guardar": {
                "no guardes",
                "no guardar",
                "descarta",
                "descartar",
                "cierra sin guardar",
                "sin guardar",
            },
            "don't save": {"don't save", "do not save", "no guardar", "descartar"},
            "cancelar": {"cancela", "cancelar", "dejalo", "dejarlo"},
            "cancel": {"cancel", "cancela", "cancelar"},
            "permitir": {"permite", "permitir", "si permite", "acepta"},
            "allow": {"allow", "permite", "permitir"},
            "aceptar": {"acepta", "aceptar", "de acuerdo"},
            "ok": {"ok", "acepta", "de acuerdo"},
            "denegar": {"deniega", "denegar", "rechaza", "no permitas"},
            "deny": {"deny", "deniega", "rechaza"},
            "no": {"no", "rechaza"},
            "si": {"si", "acepta"},
            "yes": {"yes", "si", "acepta"},
        }
        for normalized, original in normalized_options:
            candidates = {normalized, f"opcion {normalized}", *aliases.get(normalized, set())}
            if command in candidates:
                return original
        return None

    @staticmethod
    def _dialog_action(dialog: PendingDialog) -> PreparedAction:
        return PreparedAction(
            name=ActionName.DIALOG_CHOOSE,
            arguments={
                "parent_handle": dialog.parent_handle,
                "dialog_handle": dialog.dialog_handle,
                "dialog_title": dialog.title,
                "dialog_message": dialog.message,
                "options": list(dialog.options),
            },
            risk=ActionRisk.MEDIUM,
            description=f"Responder al diálogo {dialog.title}",
            source=ActionSource.CONFIRMATION,
        )

    def _dialog_outcome(
        self,
        dialog: PendingDialog,
        prefix: str = "Apareció un diálogo que necesita tu decisión.",
    ) -> ActionOutcome:
        message = f" {dialog.message}" if dialog.message else ""
        options = ", ".join(dialog.options)
        return ActionOutcome(
            status=ActionStatus.PENDING,
            message=f"{prefix}{message} Opciones: {options}. ¿Qué quieres que haga?",
            action_id=dialog.action_id,
            name=ActionName.DIALOG_CHOOSE,
            risk=ActionRisk.MEDIUM,
            description=f"Responder al diálogo {dialog.title}",
            requires_confirmation=True,
            details={
                "dialog_title": dialog.title,
                "dialog_message": dialog.message,
                "dialog_options": list(dialog.options),
            },
        )

    def _request_dialog(self, session_id: str, payload: object) -> ActionOutcome | None:
        if not isinstance(payload, dict):
            return None
        parent_handle = payload.get("parent_handle")
        dialog_handle = payload.get("dialog_handle")
        title = payload.get("title")
        message = payload.get("message", "")
        raw_options = payload.get("options")
        if (
            isinstance(parent_handle, bool)
            or not isinstance(parent_handle, int)
            or isinstance(dialog_handle, bool)
            or not isinstance(dialog_handle, int)
            or not isinstance(title, str)
            or not isinstance(message, str)
            or not isinstance(raw_options, list)
        ):
            return None
        options = tuple(
            option.strip()[:120]
            for option in raw_options[:8]
            if isinstance(option, str) and option.strip()
        )
        if not options:
            return None
        now = time.monotonic()
        dialog = PendingDialog(
            action_id=uuid4().hex,
            session_id=session_id,
            parent_handle=parent_handle,
            dialog_handle=dialog_handle,
            title=title.strip()[:200] or "Diálogo de Windows",
            message=message.strip()[:600],
            options=options,
            created_at=now,
        )
        self._dialogs[session_id] = dialog
        self._dialogs.move_to_end(session_id)
        while len(self._dialogs) > max(1, self.settings.max_sessions):
            self._dialogs.popitem(last=False)
        outcome = self._dialog_outcome(dialog)
        self.audit.record(session_id, self._dialog_action(dialog), outcome)
        return outcome

    async def decide(
        self,
        session_id: str,
        action_id: str,
        approve: bool | None,
        choice: str | None = None,
    ) -> ActionOutcome:
        self._prune_pending()
        dialog = self._dialogs.get(session_id)
        if dialog is not None and dialog.action_id == action_id:
            selected = (
                self._match_dialog_choice(normalize_request(choice), dialog.options)
                if isinstance(choice, str) and choice.strip()
                else None
            )
            if selected is None and approve is False:
                selected = self._match_dialog_choice("cancelar", dialog.options)
            if selected is None:
                return self._dialog_outcome(
                    dialog,
                    prefix="Necesito que elijas una opción concreta; no asumiré una respuesta.",
                )
            return await self._decide_dialog(session_id, action_id, selected)
        pending = self._pending.get(session_id)
        if pending is None or pending.action_id != action_id:
            return ActionOutcome(
                status=ActionStatus.REJECTED,
                message="La confirmación no existe, expiró o pertenece a otra sesión.",
            )
        self._pending.pop(session_id, None)
        if approve is not True:
            outcome = ActionOutcome(
                status=ActionStatus.CANCELLED,
                message="Acción cancelada. No realicé ningún cambio.",
                action_id=action_id,
                name=pending.action.name,
                risk=pending.action.risk,
                description=pending.action.description,
            )
            self.audit.record(session_id, pending.action, outcome)
            return outcome
        return await self._execute(session_id, pending.action, action_id)

    async def _decide_dialog(
        self,
        session_id: str,
        action_id: str,
        choice: str,
    ) -> ActionOutcome:
        dialog = self._dialogs.get(session_id)
        if dialog is None or dialog.action_id != action_id:
            return ActionOutcome(
                status=ActionStatus.REJECTED,
                message="El diálogo ya no existe, expiró o pertenece a otra sesión.",
            )
        self._dialogs.pop(session_id, None)
        result = await self.catalog.choose_dialog_option(
            dialog.parent_handle,
            dialog.dialog_handle,
            choice,
        )
        action = self._dialog_action(dialog)
        if result.details.get("dialog_confirmation_required") is True:
            completed = ActionOutcome(
                status=ActionStatus.COMPLETED,
                message=result.message,
                action_id=action_id,
                name=ActionName.DIALOG_CHOOSE,
                risk=ActionRisk.MEDIUM,
                description=action.description,
                details={"choice": choice, "verified": True},
            )
            self.audit.record(session_id, action, completed)
            waiting = self._request_dialog(session_id, result.details.get("dialog"))
            if waiting is not None:
                return waiting
        outcome = ActionOutcome(
            status=ActionStatus.COMPLETED if result.success else ActionStatus.FAILED,
            message=result.message,
            action_id=action_id,
            name=ActionName.DIALOG_CHOOSE,
            risk=ActionRisk.MEDIUM,
            description=action.description,
            details=result.details,
        )
        self.audit.record(session_id, action, outcome)
        return outcome

    def _remember_visual_context(
        self,
        session_id: str,
        action: PreparedAction | PreparedWorkflow,
        result: ExecutionResult,
    ) -> None:
        if (
            not result.success
            or not isinstance(action, PreparedAction)
            or action.name not in self._VISUAL_ACTIONS
        ):
            return
        monitor = result.details.get("monitor", action.arguments.get("monitor", "all"))
        if not isinstance(monitor, str):
            monitor = "all"
        monitor_label = result.details.get("monitor_label")
        if not isinstance(monitor_label, str) or not monitor_label.strip():
            monitor_label = (
                "Todas las pantallas" if monitor == "all" else f"Monitor {monitor}"
            )
        previous = self._visual_contexts.get(session_id)
        same_focus = previous is not None and previous.monitor == monitor
        raw_elements = result.details.get("interactive_elements")
        if isinstance(raw_elements, list):
            elements = tuple(
                element.strip()[:200]
                for element in raw_elements[:12]
                if isinstance(element, str) and element.strip()
            )
        elif same_focus and previous is not None:
            elements = previous.interactive_elements
        else:
            elements = ()
        last_target = previous.last_target if same_focus and previous is not None else None
        if action.name in {ActionName.SCREEN_FIND, ActionName.SCREEN_CLICK}:
            target = result.details.get("target", action.arguments.get("target"))
            if isinstance(target, str) and target.strip():
                last_target = target.strip()[:300]
        elif action.name is ActionName.SCREEN_DESCRIBE and len(elements) == 1:
            last_target = elements[0]
        summary = next(
            (
                value.strip()[:1_200]
                for key in ("summary", "answer")
                if isinstance((value := result.details.get(key)), str) and value.strip()
            ),
            result.message[:1_200],
        )
        self._visual_contexts[session_id] = VisualSessionContext(
            monitor=monitor,
            monitor_label=monitor_label.strip()[:120],
            summary=summary,
            interactive_elements=elements,
            last_target=last_target,
            created_at=time.monotonic(),
        )
        self._visual_contexts.move_to_end(session_id)
        while len(self._visual_contexts) > max(1, self.settings.max_sessions):
            self._visual_contexts.popitem(last=False)

    async def _execute(
        self,
        session_id: str,
        action: PreparedAction | PreparedWorkflow,
        action_id: str | None = None,
    ) -> ActionOutcome:
        try:
            async with self._execution_lock:
                result = await self.catalog.execute(action)
        except Exception as exc:
            result = ExecutionResult(
                False,
                f"La acción falló de forma controlada: {type(exc).__name__}.",
            )
        self._remember_visual_context(session_id, action, result)
        if (
            result.success
            and isinstance(action, PreparedAction)
            and action.name is ActionName.SCREEN_CLICK
            and result.details.get("pixel_confirmation_required") is True
        ):
            localized = ActionOutcome(
                status=ActionStatus.COMPLETED,
                message=result.message,
                action_id=action_id,
                name=action.name,
                risk=action.risk,
                description=action.description,
                details=result.details,
            )
            self.audit.record(session_id, action, localized)
            pointer = self.catalog.prepare(
                ActionPlan(
                    ActionName.POINTER_CLICK,
                    {"x": result.details["x"], "y": result.details["y"]},
                    source=ActionSource.CONFIRMATION,
                )
            )
            pending = self._request_confirmation(session_id, pointer)
            return replace(
                pending,
                message=(
                    f"{result.message} Necesito una segunda confirmación para hacer clic "
                    "en la posición donde quedó el cursor."
                ),
                details={
                    "cursor_moved": True,
                    "element": result.details.get("element"),
                },
            )
        if result.details.get("dialog_confirmation_required") is True:
            waiting = self._request_dialog(session_id, result.details.get("dialog"))
            if waiting is not None:
                original = ActionOutcome(
                    status=ActionStatus.PENDING,
                    message=result.message,
                    action_id=action_id,
                    name=action.name,
                    risk=action.risk,
                    description=action.description,
                    requires_confirmation=True,
                )
                self.audit.record(session_id, action, original)
                return waiting
        outcome = ActionOutcome(
            status=ActionStatus.COMPLETED if result.success else ActionStatus.FAILED,
            message=result.message,
            action_id=action_id,
            name=action.name,
            risk=action.risk,
            description=action.description,
            details=result.details,
        )
        self.audit.record(session_id, action, outcome)
        return outcome

    def reset(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
        self._dialogs.pop(session_id, None)
        self._visual_contexts.pop(session_id, None)

    def recent_audit(self, limit: int = 30):
        return self.audit.recent(limit)

    async def close(self) -> None:
        await self.catalog.close()
