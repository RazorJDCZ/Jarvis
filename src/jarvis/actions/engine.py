from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jarvis.actions.audit import ActionAuditLog
from jarvis.actions.catalog import ActionCatalog, ActionSecurityError
from jarvis.actions.decisions import ActionDecision, ActionDecisionInterpreter
from jarvis.actions.models import (
    ActionName,
    ActionOutcome,
    ActionPlan,
    ActionRisk,
    ActionSource,
    ActionStatus,
    ActionWorkflowPlan,
    AgentGoalComplete,
    BlockedIntent,
    ClarificationNeeded,
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


@dataclass(frozen=True, slots=True)
class PendingClarification:
    original_request: str
    question: str
    created_at: float


@dataclass(frozen=True, slots=True)
class AgentSessionContext:
    turns: tuple[dict[str, str], ...]
    updated_at: float


@dataclass(frozen=True, slots=True)
class ActiveAgentGoal:
    original_request: str
    remaining_rounds: int
    remaining_actions: int
    continue_after_current: bool
    remote: bool
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
    _AGENT_CONTEXT_SECONDS = 900
    _CLARIFICATION_SECONDS = 180
    _REMOTE_DIRECT_ACTIONS = frozenset(
        {
            ActionName.APP_LIST,
            ActionName.BROWSER_LIST_TABS,
            ActionName.BROWSER_READ,
            ActionName.SCREEN_LIST,
            ActionName.SYSTEM_STATUS,
            ActionName.UI_INSPECT,
            ActionName.VOLUME_GET,
            ActionName.WINDOW_CURRENT,
            ActionName.WINDOW_LIST,
            ActionName.SKILL_LIST,
            ActionName.TASK_LIST,
            ActionName.PROJECT_LIST,
            ActionName.CALENDAR_LIST,
            ActionName.INBOX_LIST,
            ActionName.FOCUS_STATUS,
            ActionName.REMINDER_LIST,
            ActionName.KNOWLEDGE_LIST,
            ActionName.KNOWLEDGE_SEARCH,
            ActionName.ATTACHMENT_LIST,
            ActionName.PERMISSION_LIST,
            ActionName.DEV_LIST,
            ActionName.DEV_INSPECT,
            ActionName.DEV_SEARCH,
            ActionName.GAME_LIST,
        }
    )
    _REMEMBERABLE_ACTIONS = frozenset(
        {
            ActionName.BROWSER_OPEN,
            ActionName.BROWSER_SEARCH,
            ActionName.BROWSER_NEW_TAB,
            ActionName.BROWSER_SWITCH_TAB,
            ActionName.VOLUME_SET,
            ActionName.VOLUME_CHANGE,
            ActionName.VOLUME_MUTE,
            ActionName.MEDIA_PLAY_PAUSE,
            ActionName.MEDIA_NEXT,
            ActionName.MEDIA_PREVIOUS,
            ActionName.MEDIA_STOP,
            ActionName.WINDOW_FOCUS,
            ActionName.WINDOW_MINIMIZE,
            ActionName.WINDOW_MAXIMIZE,
            ActionName.WINDOW_RESTORE,
            ActionName.POINTER_SCROLL,
            ActionName.DESKTOP_SHOW,
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
        self._agent_contexts: OrderedDict[str, AgentSessionContext] = OrderedDict()
        self._clarifications: OrderedDict[str, PendingClarification] = OrderedDict()
        self._agent_goals: OrderedDict[str, ActiveAgentGoal] = OrderedDict()
        self._execution_lock = asyncio.Lock()

    @property
    def capabilities(self):
        return getattr(self.catalog, "capabilities", None)

    @property
    def rememberable_actions(self) -> frozenset[str]:
        return frozenset(action.value for action in self._REMEMBERABLE_ACTIONS)

    async def start(self, callback=None) -> None:
        capabilities = self.capabilities
        if capabilities is not None:
            await capabilities.start(callback)

    async def attachment_context(
        self,
        session_id: str,
        attachment_ids: tuple[str, ...],
        question: str,
    ) -> str:
        capabilities = self.capabilities
        if capabilities is None:
            return ""
        return await capabilities.attachment_context(session_id, attachment_ids, question)

    def _permission_allows(
        self,
        action: PreparedAction | PreparedWorkflow,
        remote: bool,
        session_id: str,
    ) -> bool:
        capabilities = self.capabilities
        if capabilities is None or action.risk is ActionRisk.HIGH:
            return False
        steps = action.steps if isinstance(action, PreparedWorkflow) else (action,)
        if not steps or any(step.name not in self._REMEMBERABLE_ACTIONS for step in steps):
            return False
        return all(
            capabilities.permissions.is_allowed(
                self._permission_key(step.name, remote, session_id),
                remote,
                action.risk,
            )
            for step in steps
        )

    @staticmethod
    def _permission_key(action: ActionName, remote: bool, session_id: str) -> str:
        if not remote:
            return action.value
        parts = session_id.split(":", maxsplit=2)
        device = parts[1] if len(parts) >= 2 and parts[0] == "remote" else "unknown"
        return f"{action.value}@device:{device[:32]}"

    def _can_remember(self, action: PreparedAction | PreparedWorkflow) -> bool:
        if action.risk is ActionRisk.HIGH:
            return False
        steps = action.steps if isinstance(action, PreparedWorkflow) else (action,)
        return bool(steps) and all(step.name in self._REMEMBERABLE_ACTIONS for step in steps)

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
        expired_agent_contexts = [
            session
            for session, context in self._agent_contexts.items()
            if current - context.updated_at > self._AGENT_CONTEXT_SECONDS
        ]
        for session in expired_agent_contexts:
            self._agent_contexts.pop(session, None)
        expired_clarifications = [
            session
            for session, clarification in self._clarifications.items()
            if current - clarification.created_at > self._CLARIFICATION_SECONDS
        ]
        for session in expired_clarifications:
            self._clarifications.pop(session, None)
        expired_goals = [
            session
            for session, goal in self._agent_goals.items()
            if current - goal.created_at > self._AGENT_CONTEXT_SECONDS
        ]
        for session in expired_goals:
            self._agent_goals.pop(session, None)

    @staticmethod
    def _blocked(message: str) -> ActionOutcome:
        return ActionOutcome(status=ActionStatus.BLOCKED, message=message, risk=ActionRisk.BLOCKED)

    def _agent_context(self, session_id: str) -> tuple[dict[str, str], ...]:
        context = self._agent_contexts.get(session_id)
        return context.turns if context is not None else ()

    def _planner_context(
        self,
        session_id: str,
        conversation_context: tuple[dict[str, str], ...],
    ) -> tuple[dict[str, str], ...]:
        combined = list(self._agent_context(session_id))
        for item in conversation_context[-6:]:
            role = item.get("role", "")
            content = item.get("content", "").strip()[:500]
            if not content:
                continue
            combined.append(
                {
                    "request": content if role == "user" else "",
                    "action": "conversation-context",
                    "outcome": content if role == "assistant" else "",
                }
            )
        return tuple(combined[-4:])

    @staticmethod
    def _plan_label(plan: ActionPlan | ActionWorkflowPlan) -> str:
        if isinstance(plan, ActionWorkflowPlan):
            return " -> ".join(step.name.value for step in plan.steps)
        return plan.name.value

    def _remember_agent_turn(
        self,
        session_id: str,
        request: str,
        plan: ActionPlan | ActionWorkflowPlan,
        outcome: ActionOutcome,
    ) -> None:
        current = self._agent_contexts.get(session_id)
        turns = list(current.turns if current is not None else ())
        turns.append(
            {
                "request": request.strip()[:500],
                "action": self._plan_label(plan)[:80],
                "outcome": outcome.message.strip()[:500],
            }
        )
        now = time.monotonic()
        self._agent_contexts[session_id] = AgentSessionContext(tuple(turns[-4:]), now)
        self._agent_contexts.move_to_end(session_id)
        while len(self._agent_contexts) > max(1, self.settings.max_sessions):
            self._agent_contexts.popitem(last=False)

    def _request_clarification(
        self,
        session_id: str,
        clarification: ClarificationNeeded,
    ) -> ActionOutcome:
        self._clarifications[session_id] = PendingClarification(
            original_request=clarification.original_request,
            question=clarification.question,
            created_at=time.monotonic(),
        )
        self._clarifications.move_to_end(session_id)
        while len(self._clarifications) > max(1, self.settings.max_sessions):
            self._clarifications.popitem(last=False)
        return ActionOutcome(
            status=ActionStatus.REJECTED,
            message=clarification.question,
            details={"clarification_required": True},
        )

    def supersede_pending(self, session_id: str) -> bool:
        """Cancel a confirmation when the user moves on to another request."""
        pending = self._pending.pop(session_id, None)
        if pending is None:
            return False
        self._agent_goals.pop(session_id, None)
        outcome = ActionOutcome(
            status=ActionStatus.CANCELLED,
            message="La acción pendiente fue reemplazada por una solicitud nueva.",
            action_id=pending.action_id,
            name=pending.action.name,
            risk=pending.action.risk,
            description=pending.action.description,
        )
        self.audit.record(session_id, pending.action, outcome)
        return True

    @staticmethod
    def _plan_size(plan: ActionPlan | ActionWorkflowPlan) -> int:
        return len(plan.steps) if isinstance(plan, ActionWorkflowPlan) else 1

    def _start_agent_goal(
        self,
        session_id: str,
        request: str,
        plan: ActionPlan | ActionWorkflowPlan,
        remote: bool,
    ) -> None:
        if not plan.continue_goal:
            self._agent_goals.pop(session_id, None)
            return
        self._agent_goals[session_id] = ActiveAgentGoal(
            original_request=request.strip()[:1_000],
            remaining_rounds=self.settings.agent_max_rounds,
            remaining_actions=max(0, self.settings.agent_max_steps - self._plan_size(plan)),
            continue_after_current=True,
            remote=remote,
            created_at=time.monotonic(),
        )
        self._agent_goals.move_to_end(session_id)
        while len(self._agent_goals) > max(1, self.settings.max_sessions):
            self._agent_goals.popitem(last=False)

    async def try_handle(
        self,
        session_id: str,
        text: str,
        *,
        remote: bool = False,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> ActionOutcome | None:
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
        spoken_decision = ActionDecisionInterpreter.interpret(text)
        if spoken_decision is ActionDecision.APPROVE:
            if pending is None:
                return None
            remember = bool(re.search(r"\b(?:siempre|recuerda)\b", decision))
            return await self.decide(
                session_id,
                pending.action_id,
                approve=True,
                remember=remember,
            )
        if spoken_decision is ActionDecision.REJECT:
            if pending is not None:
                return await self.decide(session_id, pending.action_id, approve=False)
            if self._clarifications.pop(session_id, None) is not None:
                self._agent_goals.pop(session_id, None)
                return ActionOutcome(
                    status=ActionStatus.CANCELLED,
                    message="De acuerdo, descarté esa solicitud.",
                )
            return None

        # Confirmations are single-turn capabilities. Once the user starts a different
        # utterance, keeping an older mutation armed would let a later generic "sí" execute
        # the wrong action.
        if pending is not None:
            self.supersede_pending(session_id)
            pending = None

        pending_clarification = self._clarifications.get(session_id)
        if pending_clarification is None:
            # Active goals normally advance within this same request or wait behind a
            # confirmation. A new independent utterance supersedes stale autonomous work.
            self._agent_goals.pop(session_id, None)
        parsed = self.parser.parse(text)
        if isinstance(parsed, BlockedIntent):
            self._clarifications.pop(session_id, None)
            return self._blocked(parsed.reason)
        planning_text = text
        continuation = False
        if pending_clarification is not None and parsed is None:
            if not self.parser.has_agent_intent(text):
                continuation = True
                planning_text = (
                    f"Solicitud original: {pending_clarification.original_request}\n"
                    f"Aclaración del usuario: {text.strip()}"
                )
            else:
                self._clarifications.pop(session_id, None)
        elif parsed is not None:
            self._clarifications.pop(session_id, None)

        parsed = await self._expand_explicit_workflow(
            session_id,
            planning_text,
            parsed,
            conversation_context,
        )
        if isinstance(parsed, BlockedIntent):
            return self._blocked(parsed.reason)
        agent_candidate = continuation or self.parser.has_agent_intent(planning_text)
        # A short reference such as "¿qué dice ese error?" must first resolve against
        # the last verified capture. Sending it to the semantic planner without that
        # grounding can make a small model invent an invalid monitor identifier.
        if parsed is None and not continuation:
            parsed = self._apply_visual_context(session_id, text, None)
        if parsed is None and agent_candidate:
            parsed = await self.planner.plan(
                planning_text,
                self._planner_context(session_id, conversation_context),
            )
        if isinstance(parsed, ClarificationNeeded):
            original_request = (
                pending_clarification.original_request
                if continuation and pending_clarification is not None
                else text.strip()
            )
            return self._request_clarification(
                session_id,
                replace(parsed, original_request=original_request),
            )
        if isinstance(parsed, AgentGoalComplete):
            return ActionOutcome(
                status=ActionStatus.COMPLETED,
                message=parsed.message,
                details={"agent_goal_complete": True},
            )
        parsed = self._apply_visual_context(session_id, text, parsed)
        if parsed is None:
            if agent_candidate or self.parser.looks_visual(text):
                question = (
                    "Entendí que quieres que observe la pantalla. ¿Busco algo concreto o "
                    "describo todo lo visible?"
                    if self.parser.looks_visual(text)
                    else (
                        "Entendí que quieres que trabaje con la computadora, pero todavía falta "
                        "definir el resultado. ¿Qué debería quedar listo al terminar?"
                    )
                )
                return self._request_clarification(
                    session_id,
                    ClarificationNeeded(question, text.strip()[:1_000], 1.0),
                )
            return None
        self._clarifications.pop(session_id, None)
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

        self._start_agent_goal(session_id, text, resolved, remote)
        prepared = self._apply_remote_policy(prepared, remote)
        if prepared.risk in {ActionRisk.MEDIUM, ActionRisk.HIGH} and not self._permission_allows(
            prepared,
            remote,
            session_id,
        ):
            outcome = self._request_confirmation(session_id, prepared, remote=remote)
        else:
            outcome = await self._execute(session_id, prepared)
        self._remember_agent_turn(session_id, text, resolved, outcome)
        return outcome

    def _apply_remote_policy(
        self,
        action: PreparedAction | PreparedWorkflow,
        remote: bool,
    ) -> PreparedAction | PreparedWorkflow:
        if not remote:
            return action
        if isinstance(action, PreparedWorkflow):
            changes_state = any(
                step.name not in self._REMOTE_DIRECT_ACTIONS for step in action.steps
            )
            if changes_state and action.risk is ActionRisk.LOW:
                return replace(
                    action,
                    risk=ActionRisk.MEDIUM,
                    description=f"Autorizar desde el celular: {action.description}",
                )
            return action
        if action.risk is ActionRisk.LOW and action.name not in self._REMOTE_DIRECT_ACTIONS:
            return replace(
                action,
                risk=ActionRisk.MEDIUM,
                description=f"Autorizar desde el celular: {action.description}",
            )
        return action

    async def _expand_explicit_workflow(
        self,
        session_id: str,
        text: str,
        current: ActionPlan | ActionWorkflowPlan | None,
        conversation_context: tuple[dict[str, str], ...] = (),
    ) -> ActionPlan | ActionWorkflowPlan | BlockedIntent | None:
        if isinstance(current, ActionWorkflowPlan):
            return current
        parts = self.parser.workflow_parts(text)
        if not 2 <= len(parts) <= self.settings.agent_max_steps:
            return current
        steps: list[ActionPlan] = []
        for part in parts:
            candidate = self.parser.parse(part)
            if isinstance(candidate, BlockedIntent):
                return candidate
            if candidate is None and self.parser.looks_action_like(part):
                candidate = await self.planner.plan(
                    part,
                    self._planner_context(session_id, conversation_context),
                )
            if isinstance(candidate, ClarificationNeeded):
                return current
            if isinstance(candidate, ActionWorkflowPlan):
                steps.extend(candidate.steps)
            elif isinstance(candidate, ActionPlan):
                steps.append(candidate)
            else:
                return current
        if not 2 <= len(steps) <= self.settings.agent_max_steps:
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
                continue_goal=plan.continue_goal,
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
        if not 2 <= len(plan.steps) <= self.settings.agent_max_steps:
            raise ActionSecurityError(
                f"Un flujo puede contener entre dos y {self.settings.agent_max_steps} acciones."
            )
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
        *,
        remote: bool = False,
    ) -> ActionOutcome:
        now = time.monotonic()
        action_id = uuid4().hex
        pending = PendingAction(
            action_id=action_id,
            session_id=session_id,
            action=action,
            created_at=now,
            expires_at=now + max(15, self.settings.action_confirmation_seconds),
            remote=remote,
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
            details={"rememberable": self._can_remember(action)},
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
        remember: bool = False,
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
            self._agent_goals.pop(session_id, None)
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
        outcome = await self._execute(session_id, pending.action, action_id)
        if remember and outcome.status is ActionStatus.COMPLETED:
            remembered = self._remember_permission(
                pending.action,
                pending.remote,
                session_id,
            )
            if remembered:
                return replace(
                    outcome,
                    message=(
                        f"{outcome.message} Recordar\u00e9 este permiso durante 30 d\u00edas "
                        "en este contexto."
                    ),
                    details={**outcome.details, "permission_remembered": True},
                )
        return outcome

    def _remember_permission(
        self,
        action: PreparedAction | PreparedWorkflow,
        remote: bool,
        session_id: str,
    ) -> bool:
        capabilities = self.capabilities
        if capabilities is None or action.risk is ActionRisk.HIGH:
            return False
        steps = action.steps if isinstance(action, PreparedWorkflow) else (action,)
        if not steps or any(step.name not in self._REMEMBERABLE_ACTIONS for step in steps):
            return False
        expires_at = datetime.now(UTC) + timedelta(days=30)
        try:
            for step in steps:
                capabilities.permissions.set(
                    self._permission_key(step.name, remote, session_id),
                    remote,
                    "allow",
                    expires_at,
                )
        except (OSError, ValueError):
            return False
        return True

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
            monitor_label = "Todas las pantallas" if monitor == "all" else f"Monitor {monitor}"
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

    async def _advance_agent_goal(
        self,
        session_id: str,
        previous: ActionOutcome,
    ) -> ActionOutcome:
        goal = self._agent_goals.get(session_id)
        if goal is None or not goal.continue_after_current:
            self._agent_goals.pop(session_id, None)
            return previous
        if goal.remaining_rounds <= 0 or goal.remaining_actions <= 0:
            self._agent_goals.pop(session_id, None)
            return replace(
                previous,
                message=(
                    f"{previous.message} Detuve el objetivo al alcanzar el límite seguro de "
                    "planificación; puedes pedirme que continúe desde este resultado."
                ),
                details={**previous.details, "agent_limit_reached": True},
            )

        observation = {
            "request": goal.original_request,
            "action": "verified-observation",
            "outcome": previous.message.strip()[:1_200],
        }
        planning_request = (
            "Continúa el objetivo original usando la observación verificada más reciente. "
            "No repitas pasos completados.\n"
            f"Objetivo original: {goal.original_request}"
        )
        decision = await self.planner.plan(
            planning_request,
            (*self._planner_context(session_id, ()), observation),
        )
        if isinstance(decision, AgentGoalComplete):
            self._agent_goals.pop(session_id, None)
            return replace(
                previous,
                message=decision.message,
                details={**previous.details, "agent_goal_complete": True},
            )
        if isinstance(decision, ClarificationNeeded):
            self._agent_goals.pop(session_id, None)
            return self._request_clarification(
                session_id,
                replace(decision, original_request=goal.original_request),
            )
        if not isinstance(decision, ActionPlan | ActionWorkflowPlan):
            self._agent_goals.pop(session_id, None)
            return replace(
                previous,
                message=(
                    f"{previous.message} Verifiqué ese avance, pero no pude deducir con "
                    "seguridad el siguiente paso. ¿Qué criterio quieres que use para continuar?"
                ),
                details={**previous.details, "clarification_required": True},
            )

        action_count = self._plan_size(decision)
        if action_count > goal.remaining_actions:
            self._agent_goals.pop(session_id, None)
            return replace(
                previous,
                message=(
                    f"{previous.message} El siguiente plan excedería el límite seguro de "
                    "acciones. Puedes pedirme que continúe desde aquí."
                ),
                details={**previous.details, "agent_limit_reached": True},
            )
        resolved = self._apply_visual_context(session_id, goal.original_request, decision)
        if resolved is None:
            self._agent_goals.pop(session_id, None)
            return previous
        try:
            prepared = self._prepare(resolved)
        except ActionSecurityError as exc:
            self._agent_goals.pop(session_id, None)
            return self._blocked(str(exc))
        except Exception as exc:
            self._agent_goals.pop(session_id, None)
            return ActionOutcome(
                status=ActionStatus.FAILED,
                message=f"No pude preparar el siguiente paso: {type(exc).__name__}.",
            )

        self._agent_goals[session_id] = replace(
            goal,
            remaining_rounds=goal.remaining_rounds - 1,
            remaining_actions=goal.remaining_actions - action_count,
            continue_after_current=resolved.continue_goal,
        )
        prepared = self._apply_remote_policy(prepared, goal.remote)
        if prepared.risk in {ActionRisk.MEDIUM, ActionRisk.HIGH} and not self._permission_allows(
            prepared,
            goal.remote,
            session_id,
        ):
            return self._request_confirmation(session_id, prepared, remote=goal.remote)
        return await self._execute(session_id, prepared)

    async def _execute(
        self,
        session_id: str,
        action: PreparedAction | PreparedWorkflow,
        action_id: str | None = None,
    ) -> ActionOutcome:
        try:
            async with self._execution_lock:
                if getattr(self.catalog, "session_aware", False):
                    result = await self.catalog.execute(action, session_id=session_id)
                else:
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
            self._agent_goals.pop(session_id, None)
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
        if outcome.status is ActionStatus.COMPLETED:
            return await self._advance_agent_goal(session_id, outcome)
        self._agent_goals.pop(session_id, None)
        return outcome

    def reset(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
        self._dialogs.pop(session_id, None)
        self._visual_contexts.pop(session_id, None)
        self._agent_contexts.pop(session_id, None)
        self._clarifications.pop(session_id, None)
        self._agent_goals.pop(session_id, None)

    def emergency_stop(self, session_id: str) -> dict[str, int]:
        cancelled_actions = int(self._pending.pop(session_id, None) is not None)
        cancelled_dialogs = int(self._dialogs.pop(session_id, None) is not None)
        cancelled_clarifications = int(self._clarifications.pop(session_id, None) is not None)
        cancelled_agent_goals = int(self._agent_goals.pop(session_id, None) is not None)
        return {
            "pending_actions": cancelled_actions,
            "pending_dialogs": cancelled_dialogs,
            "pending_clarifications": cancelled_clarifications,
            "active_agent_goals": cancelled_agent_goals,
        }

    def pending_for(self, session_id: str) -> ActionOutcome | None:
        self._prune_pending()
        dialog = self._dialogs.get(session_id)
        if dialog is not None:
            return self._dialog_outcome(dialog, prefix="Hay un diálogo esperando tu decisión.")
        pending = self._pending.get(session_id)
        if pending is None:
            return None
        return ActionOutcome(
            status=ActionStatus.PENDING,
            message=f"Sigue pendiente: {pending.action.description}.",
            action_id=pending.action_id,
            name=pending.action.name,
            risk=pending.action.risk,
            description=pending.action.description,
            requires_confirmation=True,
        )

    def recent_audit(self, limit: int = 30):
        return self.audit.recent(limit)

    async def close(self) -> None:
        await self.catalog.close()
