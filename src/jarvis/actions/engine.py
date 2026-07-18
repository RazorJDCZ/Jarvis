from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import replace
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
    PreparedAction,
    PreparedWorkflow,
)
from jarvis.actions.parser import DeterministicActionParser, normalize_request
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


class ActionEngine:
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
        self._last_visual_targets: OrderedDict[str, tuple[str, float]] = OrderedDict()
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
        expired_targets = [
            session
            for session, (_, created_at) in self._last_visual_targets.items()
            if current - created_at > 120
        ]
        for session in expired_targets:
            self._last_visual_targets.pop(session, None)

    @staticmethod
    def _blocked(message: str) -> ActionOutcome:
        return ActionOutcome(status=ActionStatus.BLOCKED, message=message, risk=ActionRisk.BLOCKED)

    async def try_handle(self, session_id: str, text: str) -> ActionOutcome | None:
        self._prune_pending()
        command = normalize_request(text)
        decision = re.sub(r"[,;.!?]+", " ", command)
        decision = re.sub(r"\s+", " ", decision).strip()
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
                context = self._last_visual_targets.get(session_id)
                if context is None:
                    return None
                return ActionPlan(
                    name=step.name,
                    arguments={"target": context[0]},
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

    async def decide(
        self,
        session_id: str,
        action_id: str,
        approve: bool,
    ) -> ActionOutcome:
        self._prune_pending()
        pending = self._pending.get(session_id)
        if pending is None or pending.action_id != action_id:
            return ActionOutcome(
                status=ActionStatus.REJECTED,
                message="La confirmación no existe, expiró o pertenece a otra sesión.",
            )
        self._pending.pop(session_id, None)
        if not approve:
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
        outcome = ActionOutcome(
            status=ActionStatus.COMPLETED if result.success else ActionStatus.FAILED,
            message=result.message,
            action_id=action_id,
            name=action.name,
            risk=action.risk,
            description=action.description,
            details=result.details,
        )
        if (
            result.success
            and isinstance(action, PreparedAction)
            and action.name is ActionName.SCREEN_FIND
            and isinstance(result.details.get("target"), str)
        ):
            self._last_visual_targets[session_id] = (
                result.details["target"],
                time.monotonic(),
            )
            self._last_visual_targets.move_to_end(session_id)
            while len(self._last_visual_targets) > max(1, self.settings.max_sessions):
                self._last_visual_targets.popitem(last=False)
        self.audit.record(session_id, action, outcome)
        return outcome

    def reset(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
        self._last_visual_targets.pop(session_id, None)

    def recent_audit(self, limit: int = 30):
        return self.audit.recent(limit)

    async def close(self) -> None:
        await self.catalog.close()
