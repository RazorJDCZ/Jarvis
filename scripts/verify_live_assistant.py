"""Exercise the running local service with synthetic conversation/audio, no desktop changes."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx


async def main():
    session = "upgrade-check-" + uuid.uuid4().hex
    report = {"transport": "desktop loopback; phone network not measured", "text": []}
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8765", timeout=180, trust_env=False
    ) as client:

        async def stream(path, **kwargs):
            started = time.perf_counter()
            first = None
            final = None
            async with client.stream("POST", path, **kwargs) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    assert event["event"] != "error", event
                    if event["event"] == "token" and first is None:
                        first = round((time.perf_counter() - started) * 1000)
                    if event["event"] == "done":
                        final = event
            assert final and final.get("response"), final
            return {
                "first_text_ms": first,
                "total_ms": round((time.perf_counter() - started) * 1000),
                "provider": final["provider"],
                "timings_ms": final["timings_ms"],
            }, final

        try:
            for message in (
                "Dime la hora",
                "Cuéntame una historia breve sobre un robot cocinero. Máximo dos frases.",
                "Cuéntame otra historia sobre un robot jardinero. Máximo dos frases.",
            ):
                result, final = await stream(
                    "/api/chat/stream", json={"message": message, "session_id": session}
                )
                if message.startswith("Cuéntame"):
                    assert final["action"] is None, "Conversación desviada a acciones"
                    assert result["first_text_ms"] is not None, "Faltó transmisión progresiva"
                report["text"].append(result)
                print(json.dumps(result), flush=True)
            started = time.perf_counter()
            audio = await client.post("/api/tts", json={"text": "Dime la hora."})
            audio.raise_for_status()
            assert audio.content.startswith(b"RIFF")
            report["tts_ms"] = round((time.perf_counter() - started) * 1000)
            report["voice"] = []
            for _ in range(2):
                result, final = await stream(
                    "/api/voice/stream",
                    files={"audio": ("synthetic.wav", audio.content, "audio/wav")},
                    data={"session_id": session, "wake_mode": "false"},
                )
                assert final["accepted"] and "hora" in final["transcript"].lower()
                report["voice"].append(result)
                print(json.dumps(result), flush=True)
        finally:
            reset = await client.delete(f"/api/conversation/{session}")
            reset.raise_for_status()
    target = Path(__file__).resolve().parents[1] / ".data" / "live-assistant-verification.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(str(target))


if __name__ == "__main__":
    asyncio.run(main())
