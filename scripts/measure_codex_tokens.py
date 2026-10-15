"""Measure server-reported Codex tokens for representative Jarvis reasoning turns.

This is an opt-in live test: it uses the ChatGPT session configured in Codex, but it
never executes an action. Persistent Jarvis data is replaced by a temporary directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.models import ActionPlan, ActionWorkflowPlan
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings, build_system_prompt
from jarvis.providers.brain import CodexBrain
from jarvis.providers.codex_app_server import CodexAppServerClient


def _decision_summary(decision: object) -> dict[str, object]:
    if isinstance(decision, ActionPlan):
        return {
            "kind": "action",
            "name": decision.name.value,
            "source": decision.source.value,
            "confidence": decision.confidence,
        }
    if isinstance(decision, ActionWorkflowPlan):
        return {
            "kind": "workflow",
            "steps": [step.name.value for step in decision.steps],
            "source": decision.source.value,
            "confidence": decision.confidence,
        }
    return {"kind": type(decision).__name__ if decision is not None else "none"}


def _latest_usage(
    client: CodexAppServerClient,
    previous_count: int,
) -> dict[str, str | int]:
    history = client.token_usage_history()
    if len(history) <= previous_count:
        raise RuntimeError("Codex no reporto telemetria de tokens para el turno")
    return history[-1]


async def measure(runs: int) -> dict[str, object]:
    with TemporaryDirectory(prefix="jarvis-codex-token-test-") as directory:
        settings = Settings(
            project_root=Path(directory),
            brain_mode="codex",
            codex_model="gpt-5.6-luna",
            codex_deep_model="gpt-5.6-luna",
            codex_effort="high",
            codex_deep_effort="high",
            codex_action_effort="high",
            memory_enabled=False,
            semantic_enabled=False,
            vision_actions_enabled=False,
            voice_preload=False,
        )
        client = CodexAppServerClient(settings)
        brain = CodexBrain(settings, client)
        catalog = ActionCatalog(settings.data_dir, settings.browser_search_url, settings)
        planner = LocalActionPlanner(settings, catalog.action_names, codex_client=client)
        samples: list[dict[str, object]] = []
        try:
            system_prompt = build_system_prompt(
                profile_context=(
                    "Perfil sintetico de prueba: Juan Diego estudia y prefiere respuestas claras."
                ),
                recent_context="Juan Diego: Estoy organizando mi tarde.",
                verification_context="No hay evidencia externa necesaria para esta consulta.",
            )
            for run in range(1, runs + 1):
                before = len(client.token_usage_history())
                response = await brain.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                "Ayudame a priorizar estudio, ejercicio y descanso esta tarde "
                                "en tres frases breves."
                            ),
                        },
                    ]
                )
                samples.append(
                    {
                        "run": run,
                        "scenario": "conversation",
                        "result_preview": response[:160],
                        "usage": _latest_usage(client, before),
                    }
                )

                before = len(client.token_usage_history())
                decision = await planner.plan(
                    'Abre el bloc de notas y escribe "Plan de estudio de esta tarde".'
                )
                samples.append(
                    {
                        "run": run,
                        "scenario": "action_planning_no_execution",
                        "decision": _decision_summary(decision),
                        "usage": _latest_usage(client, before),
                    }
                )
        finally:
            await catalog.close()
            await brain.close()

    usage_rows = [sample["usage"] for sample in samples]
    numeric_fields = (
        "total_tokens",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    totals = {
        field: sum(int(row.get(field, 0)) for row in usage_rows if isinstance(row, dict))
        for field in numeric_fields
    }
    return {
        "model": "gpt-5.6-luna",
        "effort": "high",
        "runs": runs,
        "turns": len(samples),
        "note": (
            "input_tokens incluye tokens cacheados; uncached_input_tokens es input menos cache."
        ),
        "samples": samples,
        "totals": totals,
        "average_per_turn": {
            field: round(value / len(samples), 2) for field, value in totals.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mide tokens reales de gpt-5.6-luna en conversacion y planificacion Jarvis."
    )
    parser.add_argument("--runs", type=int, default=1, choices=range(1, 11))
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(measure(arguments.runs)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
