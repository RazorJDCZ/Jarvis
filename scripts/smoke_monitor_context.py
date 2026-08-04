from __future__ import annotations

import argparse
import asyncio
import json
import time

from jarvis.actions.vision import LocalVisionController
from jarvis.config import Settings
from jarvis.providers.brain import OllamaBrain


async def verify(monitor: str = "all") -> dict[str, object]:
    settings = Settings()
    brain = OllamaBrain(settings)
    started = time.perf_counter()
    await brain.warmup()
    warmup_seconds = time.perf_counter() - started

    vision = LocalVisionController(settings)
    inventory = vision.list_monitors()
    started = time.perf_counter()
    observation = await vision.describe(monitor)
    return {
        "warmup_seconds": round(warmup_seconds, 2),
        "vision_seconds": round(time.perf_counter() - started, 2),
        "inventory": inventory.message,
        "success": observation.success,
        "message": observation.message,
        "monitor_observations": observation.details.get("monitor_observations", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor", default="all")
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(verify(arguments.monitor)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
