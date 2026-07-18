from __future__ import annotations

import asyncio
import importlib.util
import io
import wave
from typing import Any

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


class PiperTTS:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._voice: Any | None = None
        self._load_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()

    async def status(self) -> ProviderStatus:
        package_installed = importlib.util.find_spec("piper") is not None
        model_exists = self.settings.piper_model.exists()
        available = package_installed and model_exists
        if available:
            detail = "Voz neural local lista"
        elif not package_installed:
            detail = "Piper no instalado; se usara la voz local de Windows"
        else:
            detail = "Falta el modelo Piper; se usara la voz local de Windows"
        return ProviderStatus(
            available=available,
            name="Piper / es_ES-sharvard" if available else "Voz de Windows",
            detail=detail,
        )

    async def _ensure_voice(self) -> Any:
        if self._voice is not None:
            return self._voice
        async with self._load_lock:
            if self._voice is None:
                from piper import PiperVoice

                self._voice = await asyncio.to_thread(
                    PiperVoice.load,
                    str(self.settings.piper_model),
                )
        return self._voice

    async def synthesize(self, text: str) -> bytes:
        status = await self.status()
        if not status.available:
            raise RuntimeError(status.detail)
        voice = await self._ensure_voice()

        def _run() -> bytes:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
            return buffer.getvalue()

        async with self._synthesis_lock:
            return await asyncio.to_thread(_run)
