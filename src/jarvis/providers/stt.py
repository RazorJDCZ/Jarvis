from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


class WhisperTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def status(self) -> ProviderStatus:
        installed = importlib.util.find_spec("faster_whisper") is not None
        if not installed:
            return ProviderStatus(
                available=False,
                name="Whisper",
                detail="Dependencia faster-whisper no instalada",
            )
        loaded = "cargado" if self._model is not None else "se cargara con la primera frase"
        return ProviderStatus(
            available=True,
            name=f"Whisper / {self.settings.stt_model}",
            detail=f"Motor local {loaded}",
        )

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            from faster_whisper import WhisperModel

            self._model = await asyncio.to_thread(
                WhisperModel,
                self.settings.stt_model_reference,
                device=self.settings.stt_device,
                compute_type=self.settings.stt_compute_type,
                download_root=str(self.settings.project_root / "models" / "whisper" / ".cache"),
            )
        return self._model

    async def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        model = await self._ensure_model()

        def _run() -> tuple[str, str | None]:
            segments, info = model.transcribe(
                str(audio_path),
                language=self.settings.stt_language or None,
                beam_size=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text, getattr(info, "language", None)

        return await asyncio.to_thread(_run)
