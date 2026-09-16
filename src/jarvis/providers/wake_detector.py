from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path


class LightweightWakeDetector:
    """Opt-in 'Hey Jarvis' gate; plain 'Jarvis' keeps the compatible Whisper path."""

    def __init__(self, root: Path):
        self.root = root
        self._model = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return all(
            (self.root / name).is_file()
            for name in (
                "hey_jarvis_v0.1.onnx",
                "melspectrogram.onnx",
                "embedding_model.onnx",
            )
        )

    async def detects(self, audio: bytes) -> bool | None:
        if not self.available:
            return None
        async with self._lock:
            try:
                return await asyncio.to_thread(self._detect, audio)
            except (ImportError, OSError, ValueError, wave.Error):
                return None

    def _detect(self, audio: bytes) -> bool | None:
        import numpy as np
        from openwakeword.model import Model

        with wave.open(io.BytesIO(audio)) as reader:
            if (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) != (
                16000,
                1,
                2,
            ):
                return None
            samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype=np.int16)
        if self._model is None:
            self._model = Model(
                wakeword_models=[str(self.root / "hey_jarvis_v0.1.onnx")],
                inference_framework="onnx",
                melspec_model_path=str(self.root / "melspectrogram.onnx"),
                embedding_model_path=str(self.root / "embedding_model.onnx"),
            )
        self._model.reset()
        for start in range(0, len(samples), 1280):
            chunk = samples[start : start + 1280]
            if len(chunk) < 1280:
                chunk = np.pad(chunk, (0, 1280 - len(chunk)))
            scores = self._model.predict(chunk)
            if max(scores.values(), default=0) >= 0.35:
                return True
        return False
