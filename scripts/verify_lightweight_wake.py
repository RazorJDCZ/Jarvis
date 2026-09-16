from __future__ import annotations

import asyncio
import io
import json
import time
import wave

import numpy as np

from jarvis.config import Settings
from jarvis.providers.tts import PiperTTS
from jarvis.providers.wake_detector import LightweightWakeDetector


async def main():
    settings = Settings()
    tts = PiperTTS(settings)
    engine = await tts._ensure_kokoro()
    detector = LightweightWakeDetector(settings.project_root / "models" / "wake")
    results = []
    for text, lang, voice, expected in (
        ("Hey Jarvis, what time is it?", "en-us", "am_michael", True),
        ("Hey Jarvis", "en-us", "af_heart", True),
        ("Voy a preparar café y después estudiar.", "es", "em_alex", False),
        ("Please tell me what time it is.", "en-us", "am_michael", False),
    ):
        samples, rate = await asyncio.to_thread(engine.create, text, voice=voice, lang=lang)
        audio = np.interp(
            np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples
        )
        audio = np.concatenate([np.zeros(8000), audio, np.zeros(16000)])
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes((audio.clip(-1, 1) * 32767).astype(np.int16).tobytes())
        started = time.perf_counter()
        detected = await detector.detects(buffer.getvalue())
        item = {
            "text": text,
            "expected": expected,
            "detected": detected,
            "ms": round((time.perf_counter() - started) * 1000),
        }
        results.append(item)
        print(item, flush=True)
    (settings.data_dir / "wake-benchmark.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    assert all(item["detected"] == item["expected"] for item in results), results


if __name__ == "__main__":
    asyncio.run(main())
