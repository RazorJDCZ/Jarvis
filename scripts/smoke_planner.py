from __future__ import annotations

import asyncio
import json

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import ActionPlan, ActionWorkflowPlan, ClarificationNeeded
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings


def summarize(
    result: ActionPlan | ActionWorkflowPlan | ClarificationNeeded | None,
) -> object:
    if isinstance(result, ActionWorkflowPlan):
        return {
            "kind": "workflow",
            "steps": [step.name.value for step in result.steps],
            "confidence": result.confidence,
            "continue_goal": result.continue_goal,
        }
    if isinstance(result, ActionPlan):
        return {
            "kind": "action",
            "name": result.name.value,
            "confidence": result.confidence,
            "arguments": result.arguments,
            "continue_goal": result.continue_goal,
        }
    if isinstance(result, ClarificationNeeded):
        return {
            "kind": "clarification",
            "question": result.question,
            "confidence": result.confidence,
        }
    return None


async def verify() -> dict[str, object]:
    settings = Settings()
    catalog = ActionCatalog(settings.data_dir, settings.browser_search_url, settings)
    planner = LocalActionPlanner(settings, catalog.action_names)
    single = await planner.plan("deja el sonido aproximadamente a la mitad")
    app = await planner.plan("quiero tener el bloc de notas abierto")
    adaptive = await planner.plan(
        "necesito que compares tres cursos gratuitos de Python y abras el mejor"
    )
    engine = ActionEngine(settings, catalog=catalog, planner=planner)
    workflow_outcome = await engine.try_handle(
        "planner-smoke",
        'quiero tener el bloc de notas abierto y después escribe "hola desde jarvis"',
    )
    pending = engine._pending.get("planner-smoke")
    workflow_steps = (
        [step.name.value for step in pending.action.steps]
        if pending is not None and hasattr(pending.action, "steps")
        else []
    )
    return {
        "single": summarize(single),
        "app": summarize(app),
        "adaptive": summarize(adaptive),
        "workflow": {
            "status": workflow_outcome.status.value if workflow_outcome else None,
            "name": workflow_outcome.name.value
            if workflow_outcome and workflow_outcome.name
            else None,
            "message": workflow_outcome.message if workflow_outcome else None,
            "steps": workflow_steps,
        },
    }


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
