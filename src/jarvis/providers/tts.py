from __future__ import annotations

import asyncio
import importlib.util
import io
import wave
from typing import Any

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


class PiperTTS:
    """Local neural speech with Kokoro first and Piper as a reliable fallback.

    The historical class name is kept so existing API and scripts remain compatible.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._kokoro: Any | None = None
        self._kokoro_failed = False
        self._voice: Any | None = None
        self._load_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()

    def _kokoro_ready(self) -> bool:
        return not self._kokoro_failed and (self._kokoro is not None or (
            importlib.util.find_spec("kokoro_onnx") is not None
            and importlib.util.find_spec("soundfile") is not None
            and self.settings.kokoro_model.is_file()
            and self.settings.kokoro_voices.is_file()
        ))

    def _piper_ready(self) -> bool:
        return self._voice is not None or (
            importlib.util.find_spec("piper") is not None
            and self.settings.piper_model.is_file()
        )

    async def status(self) -> ProviderStatus:
        if self._kokoro_ready():
            return ProviderStatus(
                available=True,
                name=f"Kokoro 82M / {self.settings.kokoro_voice}",
                detail="Voz masculina neural local de alta naturalidad; Piper queda como respaldo",
            )
        if self._piper_ready():
            return ProviderStatus(
                available=True,
                name="Piper / es_ES-sharvard",
                detail="Voz neural local lista; falta Kokoro y se usa el respaldo Piper",
            )
        return ProviderStatus(
            available=False,
            name="Voz de Windows",
            detail="Faltan los modelos de voz locales; se usará la voz instalada en Windows",
        )

    async def _ensure_kokoro(self) -> Any:
        if self._kokoro is not None:
            return self._kokoro
        async with self._load_lock:
            if self._kokoro is None:
                from kokoro_onnx import Kokoro

                self._kokoro = await asyncio.to_thread(
                    Kokoro,
                    str(self.settings.kokoro_model),
                    str(self.settings.kokoro_voices),
                )
        return self._kokoro

    async def _ensure_piper(self) -> Any:
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

    async def _synthesize_kokoro(self, text: str) -> bytes:
        engine = await self._ensure_kokoro()

        def _run() -> bytes:
            import soundfile as sf

            available_voices = set(engine.voices)
            voice = self.settings.kokoro_voice
            if voice not in available_voices:
                voice = "em_alex" if "em_alex" in available_voices else "em_santa"
            samples, sample_rate = engine.create(
                text,
                voice=voice,
                speed=max(0.75, min(self.settings.kokoro_speed, 1.25)),
                lang="es",
            )
            buffer = io.BytesIO()
            sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
            return buffer.getvalue()

        return await asyncio.to_thread(_run)

    async def _synthesize_piper(self, text: str) -> bytes:
        voice = await self._ensure_piper()

        def _run() -> bytes:
            from piper.config import SynthesisConfig

            synthesis_config = SynthesisConfig(
                speaker_id=max(0, self.settings.piper_speaker_id),
                length_scale=max(0.75, min(self.settings.piper_length_scale, 1.5)),
                noise_scale=max(0.0, min(self.settings.piper_noise_scale, 1.5)),
                noise_w_scale=max(0.0, min(self.settings.piper_noise_w_scale, 1.5)),
                normalize_audio=True,
                volume=max(0.1, min(self.settings.piper_volume, 1.5)),
            )
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file, syn_config=synthesis_config)
            return buffer.getvalue()

        return await asyncio.to_thread(_run)

    async def synthesize(self, text: str) -> bytes:
        async with self._synthesis_lock:
            if self._kokoro_ready():
                try:
                    return await self._synthesize_kokoro(text)
                except Exception as exc:
                    self._kokoro_failed = True
                    if not self._piper_ready():
                        raise RuntimeError(
                            "La voz Kokoro local no pudo sintetizar el audio"
                        ) from exc
            if self._piper_ready():
                try:
                    return await self._synthesize_piper(text)
                except Exception as exc:
                    raise RuntimeError(
                        "La voz Piper de respaldo no pudo sintetizar el audio"
                    ) from exc
            status = await self.status()
            raise RuntimeError(status.detail)
