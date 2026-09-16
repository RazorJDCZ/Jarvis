"""Real local models, synthetic text/audio, and isolated knowledge data; no desktop actions."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import time
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
import psutil

from jarvis.capabilities.semantic import SemanticKnowledgeStore
from jarvis.config import Settings
from jarvis.providers.brain import OllamaBrain
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS
from jarvis.providers.wake_detector import LightweightWakeDetector
from jarvis.services.performance import active_timing, token_sink


async def main():
    config = Settings()
    report = {
        "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
        "ram_free_before_gb": round(psutil.virtual_memory().available / 2**30, 2),
    }
    messages = [
        {
            "role": "user",
            "content": "En dos frases breves, explica cómo preparar una sesión de estudio.",
        }
    ]
    baseline = OllamaBrain(replace(config, adaptive_resources=False, ollama_keep_alive="0s"))
    await baseline.release()
    started = time.perf_counter()
    baseline_answer = await baseline.chat(messages)
    report["baseline_full_text_ms"] = round((time.perf_counter() - started) * 1000)
    print("Baseline completed", flush=True)
    optimized = OllamaBrain(replace(config, adaptive_resources=True))
    for label in ("optimized_cold", "optimized_warm"):
        timing = {}
        started = time.perf_counter()

        async def receive(text, timing=timing, started=started):
            timing.setdefault("first_text_ms", round((time.perf_counter() - started) * 1000))

        sink = token_sink.set(receive)
        clock = active_timing.set(timing)
        try:
            answer = await optimized.chat(messages)
        finally:
            token_sink.reset(sink)
            active_timing.reset(clock)
        timing["full_text_ms"] = round((time.perf_counter() - started) * 1000)
        timing["characters"] = len(answer)
        report[label] = timing
        print(label, timing, flush=True)
    tts = PiperTTS(config)
    for label, text in (
        ("tts_cold", "Hey Jarvis, dime la hora."),
        ("tts_warm", "Estoy listo para ayudarte."),
    ):
        started = time.perf_counter()
        audio = await tts.synthesize(text)
        report[label + "_ms"] = round((time.perf_counter() - started) * 1000)
        if label == "tts_cold":
            wake_audio = audio
    with tempfile.TemporaryDirectory(prefix="jarvis-benchmark-") as directory:
        temp = Path(directory)
        voice_path = temp / "voice.wav"
        voice_path.write_bytes(wake_audio)
        stt = WhisperTranscriber(config)
        for label in ("stt_cold", "stt_warm"):
            started = time.perf_counter()
            transcript, _ = await stt.transcribe(voice_path)
            report[label + "_ms"] = round((time.perf_counter() - started) * 1000)
            report[label + "_transcript"] = transcript
        with wave.open(io.BytesIO(wake_audio)) as reader:
            samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype=np.int16)
            rate = reader.getframerate()
        resampled = np.interp(
            np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples
        ).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes(resampled.tobytes())
        detector = LightweightWakeDetector(config.project_root / "models" / "wake")
        started = time.perf_counter()
        report["wake_detected_synthetic_phrase"] = await detector.detects(buffer.getvalue())
        report["wake_cold_ms"] = round((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        report["wake_warm_detected"] = await detector.detects(buffer.getvalue())
        report["wake_warm_ms"] = round((time.perf_counter() - started) * 1000)
        store = SemanticKnowledgeStore(
            temp / "knowledge.db", replace(config, semantic_enabled=True)
        )
        started = time.perf_counter()
        await asyncio.to_thread(
            store.upsert_source,
            "benchmark",
            "Mecánica",
            "[Página 3]\nEl automóvil necesita gasolina para alimentar el motor de combustión.",
            "synthetic",
        )
        result = await asyncio.to_thread(
            store.search, "benchmark", "¿Qué combustible utiliza el vehículo?"
        )
        report["semantic_ms"] = round((time.perf_counter() - started) * 1000)
        report["semantic_citation"] = result[0].citation if result else None
        report["semantic_error"] = store.last_error
    await optimized.release()
    report["baseline_characters"] = len(baseline_answer)
    report["ram_free_after_gb"] = round(psutil.virtual_memory().available / 2**30, 2)
    path = config.data_dir / "assistant-benchmark.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
