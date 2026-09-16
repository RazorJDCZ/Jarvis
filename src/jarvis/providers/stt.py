from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from typing import Any

from jarvis.config import Settings
from jarvis.providers.ollama_runtime import OLLAMA_RUNTIME_LOCK
from jarvis.schemas import ProviderStatus
from jarvis.services.performance import gpu_free_mb


class WhisperTranscriber:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()
        self._transcribe_lock = asyncio.Lock()
        self._cpu_model: Any | None = None
        self._device = settings.stt_device
        self._dll_handles = []
        self.last_device = "pending"

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
            detail=f"Motor local {loaded}; dispositivo: "
            f"{self._device if self.last_device == 'pending' else self.last_device}",
        )

    def _new_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.settings.stt_model_reference,
            device=device,
            compute_type=compute_type,
            cpu_threads=max(1, min(self.settings.stt_cpu_threads, 8)),
            download_root=str(self.settings.project_root / "models" / "whisper" / ".cache"),
        )

    def _prepare_cuda(self) -> bool:
        if hasattr(os, "add_dll_directory"):
            directory = (
                self.settings.project_root / ".tools" / "ollama" / "lib" / "ollama" / "cuda_v12"
            )
            if directory.is_dir():
                self._dll_handles.append(os.add_dll_directory(str(directory)))
        try:
            import ctranslate2

            return ctranslate2.get_cuda_device_count() > 0
        except (ImportError, RuntimeError):
            return False

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            device = self.settings.stt_device
            precision = self.settings.stt_compute_type
            if device == "auto":
                free = await asyncio.to_thread(gpu_free_mb)
                cuda = await asyncio.to_thread(self._prepare_cuda)
                device = "cuda" if cuda and free is not None and free >= 1400 else "cpu"
                precision = "float16" if device == "cuda" else "int8"
            try:
                self._model = await asyncio.to_thread(self._new_model, device, precision)
            except (RuntimeError, OSError):
                if self.settings.stt_device != "auto":
                    raise
                device = "cpu"
                self._model = await asyncio.to_thread(self._new_model, "cpu", "int8")
            self._device = device
        return self._model

    async def park(self) -> None:
        async with self._transcribe_lock:
            if (
                self.settings.stt_device == "auto"
                and self._device == "cuda"
                and self._model is not None
            ):
                await asyncio.to_thread(self._model.model.unload_model, to_cpu=True)

    def _run(self, model, audio_path: Path, *, park_gpu: bool = False):
        if park_gpu:
            model.model.load_model()
        try:
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
        finally:
            if park_gpu:
                model.model.unload_model(to_cpu=True)

    async def _transcribe(self, audio_path: Path):
        async with self._transcribe_lock:
            model = await self._ensure_model()
            use_gpu = self.settings.stt_device == "auto" and self._device == "cuda"
            if use_gpu:
                free = await asyncio.to_thread(gpu_free_mb)
                if OLLAMA_RUNTIME_LOCK.locked() or (free is not None and free < 1100):
                    if self._cpu_model is None:
                        self._cpu_model = await asyncio.to_thread(self._new_model, "cpu", "int8")
                    model = self._cpu_model
                    use_gpu = False
            try:
                self.last_device = (
                    "cuda" if use_gpu else ("cpu" if model is self._cpu_model else self._device)
                )
                return await asyncio.to_thread(self._run, model, audio_path, park_gpu=use_gpu)
            except RuntimeError:
                if not use_gpu:
                    raise
                if self._cpu_model is None:
                    self._cpu_model = await asyncio.to_thread(self._new_model, "cpu", "int8")
                self.last_device = "cpu (respaldo)"
                return await asyncio.to_thread(self._run, self._cpu_model, audio_path)

    async def transcribe(self, audio_path: Path) -> tuple[str, str | None]:
        # A cancelled HTTP request cannot release the model lock while its native worker runs.
        task = asyncio.create_task(self._transcribe(audio_path))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
