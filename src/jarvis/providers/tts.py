from __future__ import annotations

import asyncio
import importlib.util
import io
import sys
import wave
from array import array
from typing import Any

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus
from jarvis.services.preferences import PreferenceStore
from jarvis.text import strip_emojis


def compress_speech_pauses(audio: bytes, max_pause_seconds: float = 0.14) -> bytes:
    """Shorten long near-silent runs without changing pitch or spoken samples."""

    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            params = source.getparams()
            if params.sampwidth != 2 or params.comptype != "NONE" or params.nchannels < 1:
                return audio
            frames = source.readframes(params.nframes)
    except (EOFError, ValueError, wave.Error):
        return audio
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    channels = params.nchannels
    frame_count = len(samples) // channels
    if not frame_count:
        return audio
    peak = max(abs(sample) for sample in samples)
    threshold = max(96, min(500, int(peak * 0.012)))
    maximum = max(1, int(params.framerate * max_pause_seconds))
    ranges = []
    start = None
    for frame in range(frame_count):
        offset = frame * channels
        silent = all(abs(samples[offset + channel]) <= threshold for channel in range(channels))
        if silent and start is None:
            start = frame
        elif not silent and start is not None:
            ranges.append((start, frame))
            start = None
    if start is not None:
        ranges.append((start, frame_count))
    long_ranges = [(start, end) for start, end in ranges if end - start > maximum]
    if not long_ranges:
        return audio
    output = array("h")
    cursor = 0
    for start, end in long_ranges:
        output.extend(samples[cursor * channels : start * channels])
        keep_before = maximum // 2
        keep_after = maximum - keep_before
        output.extend(samples[start * channels : (start + keep_before) * channels])
        output.extend(samples[(end - keep_after) * channels : end * channels])
        cursor = end
    output.extend(samples[cursor * channels :])
    if sys.byteorder != "little":
        output.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setparams(params)
        target.writeframes(output.tobytes())
    return buffer.getvalue()


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
        return not self._kokoro_failed and (
            self._kokoro is not None
            or (
                importlib.util.find_spec("kokoro_onnx") is not None
                and importlib.util.find_spec("soundfile") is not None
                and self.settings.kokoro_model.is_file()
                and self.settings.kokoro_voices.is_file()
            )
        )

    def _piper_ready(self) -> bool:
        return self._voice is not None or (
            importlib.util.find_spec("piper") is not None and self.settings.piper_model.is_file()
        )

    async def status(self) -> ProviderStatus:
        if self._kokoro_ready():
            return ProviderStatus(
                available=True,
                name=f"Kokoro 82M / {self.settings.kokoro_voice}",
                detail="Voz masculina grave Onyx; síntesis neural local con Piper como respaldo",
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

                def load():
                    import onnxruntime as ort

                    options = ort.SessionOptions()
                    options.intra_op_num_threads = 3
                    options.inter_op_num_threads = 1
                    session = ort.InferenceSession(
                        str(self.settings.kokoro_model),
                        sess_options=options,
                        providers=["CPUExecutionProvider"],
                    )
                    return Kokoro.from_session(session, str(self.settings.kokoro_voices))

                self._kokoro = await asyncio.to_thread(load)
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
            preference_store = PreferenceStore(self.settings.data_dir / "preferences.json")
            preferences = preference_store.get()
            voice = (
                preferences.voice if preference_store.path.exists() else self.settings.kokoro_voice
            )
            if voice not in available_voices:
                configured = self.settings.kokoro_voice
                if configured in available_voices:
                    voice = configured
                elif "am_onyx" in available_voices:
                    voice = "am_onyx"
                elif "em_santa" in available_voices:
                    voice = "em_santa"
                else:
                    voice = "em_alex"
            samples, sample_rate = engine.create(
                text,
                voice=voice,
                speed=preferences.voice_speed
                if preference_store.path.exists()
                else self.settings.kokoro_speed,
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

    async def _synthesize(self, text: str) -> bytes:
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

    async def synthesize(self, text: str) -> bytes:
        clean_text = strip_emojis(text)
        if not clean_text:
            raise RuntimeError("No hay texto pronunciable")
        task = asyncio.create_task(self._synthesize(clean_text))
        try:
            return compress_speech_pauses(await asyncio.shield(task))
        except asyncio.CancelledError:
            await task
            raise
