from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx


async def verify(audio_path: Path, base_url: str, wake_mode: bool) -> dict[str, object]:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=300) as client:
        deadline = time.monotonic() + 45
        while True:
            try:
                response = await client.get(f"{base_url}/api/health", timeout=0.5)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Jarvis no inició dentro del tiempo esperado") from None
                await asyncio.sleep(0.05)

        ready_at = time.perf_counter()
        with audio_path.open("rb") as audio:
            sent_at = time.perf_counter()
            response = await client.post(
                f"{base_url}/api/voice/utterance",
                files={"audio": (audio_path.name, audio, "audio/wav")},
                data={
                    "session_id": "first-start-voice-smoke",
                    "wake_mode": str(wake_mode).lower(),
                },
            )
        completed_at = time.perf_counter()
        payload = response.json()
        return {
            "status_code": response.status_code,
            "startup_wait_seconds": round(ready_at - started, 3),
            "sent_after_ready_seconds": round(sent_at - ready_at, 3),
            "response_seconds": round(completed_at - sent_at, 3),
            "payload": payload,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--wake-mode", action="store_true")
    arguments = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(verify(arguments.audio, arguments.base_url, arguments.wake_mode)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
