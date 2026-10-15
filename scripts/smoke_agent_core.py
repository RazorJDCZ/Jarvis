from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.models import (
    ActionPlan,
    ActionWorkflowPlan,
    AgentGoalComplete,
    ClarificationNeeded,
    ConversationalIntent,
)
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings

DEFAULT_CASES = (
    "quiero tener el bloc de notas abierto",
    "necesito que organices las ventanas para poder concentrarme",
    "Jarvis, ¿qué es lo que ves en mi monitor número uno?",
    "abre Chrome, busca cursos gratuitos de Python en español y lee los resultados",
)


async def _inspect(
    settings: Settings,
    cases: tuple[str, ...],
) -> list[dict[str, object]]:
    catalog = ActionCatalog(settings.data_dir, settings.browser_search_url, settings)
    planner = LocalActionPlanner(settings, catalog.action_names)
    results: list[dict[str, object]] = []
    try:
        for request in cases:
            try:
                decision = await planner.plan(request)
                if isinstance(decision, ActionPlan):
                    payload: object = {
                        "kind": "action",
                        "name": decision.name.value,
                        "arguments": decision.arguments,
                        "source": decision.source.value,
                        "confidence": decision.confidence,
                        "continue_goal": decision.continue_goal,
                    }
                elif isinstance(decision, ActionWorkflowPlan):
                    payload = {
                        "kind": "workflow",
                        "steps": [
                            {"name": step.name.value, "arguments": step.arguments}
                            for step in decision.steps
                        ],
                        "source": decision.source.value,
                        "confidence": decision.confidence,
                    }
                elif isinstance(decision, ClarificationNeeded):
                    payload = {"kind": "clarification", "question": decision.question}
                elif isinstance(decision, AgentGoalComplete):
                    payload = {"kind": "complete", "message": decision.message}
                elif isinstance(decision, ConversationalIntent):
                    payload = {"kind": "conversation"}
                else:
                    payload = None
                results.append({"request": request, "decision": payload})
            except Exception as exc:
                results.append({"request": request, "error": type(exc).__name__})
    finally:
        await planner.close()
        await catalog.close()
    return results


async def inspect(cases: tuple[str, ...]) -> list[dict[str, object]]:
    with TemporaryDirectory(prefix="jarvis-agent-smoke-") as directory:
        return await _inspect(Settings(project_root=Path(directory)), cases)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Agent Core structured decisions.")
    parser.add_argument("phrases", nargs="*", help="Natural requests to inspect")
    arguments = parser.parse_args()
    cases = tuple(arguments.phrases) or DEFAULT_CASES
    print(json.dumps(asyncio.run(inspect(cases)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
