"""End-to-end smoke test against a running Jarvis server."""

from __future__ import annotations

import asyncio

import httpx

from jarvis.config import Settings
from jarvis.providers.tts import PiperTTS


async def main() -> None:
    tts = PiperTTS(Settings())
    audio = await tts.synthesize(
        "Hola Jarvis. Preséntate brevemente y confirma que la prueba completa funciona."
    )
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            "http://127.0.0.1:8765/api/voice/utterance",
            files={"audio": ("smoke.wav", audio, "audio/wav")},
            data={"session_id": "smoke-pipeline", "wake_mode": "false"},
        )
        response.raise_for_status()
        payload = response.json()
    print(f"Transcript: {payload['transcript']}")
    print(f"Accepted: {payload['accepted']}")
    print(f"Provider: {payload['provider']}")
    print(f"Response: {payload['response']}")
    if not payload["accepted"] or not payload["response"]:
        raise RuntimeError("The complete voice pipeline did not return a response")


if __name__ == "__main__":
    asyncio.run(main())
