from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from jarvis.actions.models import ActionPlan, ActionWorkflowPlan
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings

FIXTURES = {
    "core": "agent_intents.json",
    "adversarial": "agent_intents_adversarial.json",
    "regressions": "agent_intents_regressions.json",
    "negative": "agent_intents_negative.json",
    "final": "agent_intents_final.json",
}


def load_cases(fixture_name: str, limit: int) -> list[dict[str, str]]:
    fixture_dir = Path(__file__).parents[1] / "tests" / "fixtures"
    names = ("core", "adversarial") if fixture_name == "all" else (fixture_name,)
    cases: list[dict[str, str]] = []
    for name in names:
        cases.extend(json.loads((fixture_dir / FIXTURES[name]).read_text(encoding="utf-8")))
    return cases[:limit] if limit else cases


async def unload_model(settings: Settings, model: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{settings.ollama_url}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
    except httpx.HTTPError:
        pass


async def evaluate(model: str, cases: list[dict[str, str]], keep_alive: str) -> int:
    settings = Settings(
        agent_model=model,
        agent_reasoning_enabled=False,
        agent_keep_alive=keep_alive,
    )
    planner = LocalActionPlanner(settings, tuple(LocalActionPlanner._TOOL_GUIDE))
    correct = 0
    failures: list[dict[str, object]] = []
    started = time.perf_counter()
    try:
        for index, case in enumerate(cases, start=1):
            before = time.perf_counter()
            plan = await planner.plan(case["text"])
            if isinstance(plan, ActionPlan):
                predicted = plan.name.value
            elif isinstance(plan, ActionWorkflowPlan):
                predicted = plan.steps[0].name.value if plan.steps else "none"
            else:
                predicted = "none"
            passed = predicted == case["tool"]
            correct += int(passed)
            duration = time.perf_counter() - before
            if not passed:
                failures.append(
                    {
                        "text": case["text"],
                        "expected": case["tool"],
                        "predicted": predicted,
                    }
                )
            print(
                f"{index:03d} {'OK' if passed else 'FAIL'} "
                f"expected={case['tool']} predicted={predicted} seconds={duration:.2f}",
                flush=True,
            )
    finally:
        await unload_model(settings, model)
    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "model": model,
                "accuracy": f"{correct}/{len(cases)}",
                "elapsed_seconds": round(elapsed, 2),
                "failures": failures,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if correct == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalúa el agente sin ejecutar acciones.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument(
        "--fixture",
        choices=("core", "adversarial", "regressions", "negative", "final", "all"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=0, help="0 evalúa todo el corpus")
    parser.add_argument("--keep-alive", default="5m")
    args = parser.parse_args()
    all_cases = load_cases(args.fixture, 0)
    if args.limit < 0 or args.limit > len(all_cases):
        parser.error("--limit debe ser 0 o estar dentro del tamaño del corpus")
    cases = all_cases[: args.limit] if args.limit else all_cases
    return asyncio.run(evaluate(args.model, cases, args.keep_alive))


if __name__ == "__main__":
    raise SystemExit(main())
