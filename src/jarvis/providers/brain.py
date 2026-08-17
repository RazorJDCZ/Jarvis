from __future__ import annotations

import ctypes
from datetime import datetime
from typing import Protocol

import httpx

from jarvis.config import Settings
from jarvis.providers.ollama_runtime import OLLAMA_RUNTIME_LOCK
from jarvis.schemas import ProviderStatus


class Brain(Protocol):
    name: str

    async def status(self) -> ProviderStatus: ...

    async def warmup(self) -> bool: ...

    async def release(self) -> bool: ...

    async def chat(self, messages: list[dict[str, str]]) -> str: ...

    async def chat_deep(self, messages: list[dict[str, str]]) -> str: ...


class OllamaBrain:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model_lock = OLLAMA_RUNTIME_LOCK
        self._warmed = False

    @staticmethod
    def _available_memory_gb() -> float | None:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        try:
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
            kernel32.GlobalMemoryStatusEx.restype = ctypes.c_bool
            if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            available = min(status.ullAvailPhys, status.ullAvailPageFile)
            return available / (1024**3)
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    async def status(self) -> ProviderStatus:
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(f"{self.settings.ollama_url}/api/tags")
                response.raise_for_status()
            payload = response.json()
            raw_models = payload.get("models", []) if isinstance(payload, dict) else []
            models = {
                model.get("name", "")
                for model in raw_models
                if isinstance(model, dict) and isinstance(model.get("name"), str)
            }
            wanted = self.settings.ollama_model
            installed = wanted in models or any(
                name.split(":", maxsplit=1)[0] == wanted for name in models
            )
            if installed:
                return ProviderStatus(
                    available=True,
                    name=f"Ollama / {wanted}",
                    detail=(
                        "Modelo instalado; carga bajo demanda para proteger la memoria"
                        if not self.settings.ollama_warmup_enabled
                        else "Modelo local listo"
                    ),
                )
            return ProviderStatus(
                available=False,
                name="Ollama",
                detail=f"Ollama responde, pero falta descargar {wanted}",
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return ProviderStatus(
                available=False,
                name="Ollama",
                detail="Servidor local no detectado",
            )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        return await self._chat(messages, deep_analysis=False)

    async def chat_deep(self, messages: list[dict[str, str]]) -> str:
        return await self._chat(messages, deep_analysis=True)

    async def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        deep_analysis: bool,
    ) -> str:
        async with self._model_lock:
            if self.settings.ollama_warmup_enabled and not self._warmed:
                await self._warmup_unlocked()
            payload = {
                "model": self.settings.ollama_model,
                "messages": messages,
                "stream": False,
                # Qwen's hidden thinking can consume the entire local token budget and
                # leave the spoken answer truncated. Deep mode instead uses a lower-
                # variance, larger final-answer budget guided by the analytical prompt.
                "think": False,
                "keep_alive": self.settings.ollama_keep_alive,
                "options": {
                    "temperature": 0.35 if deep_analysis else 0.45,
                    "top_p": 0.9,
                    "repeat_penalty": 1.1 if deep_analysis else 1.08,
                    "num_ctx": 8192,
                    # The spoken formats are bounded well below these limits. Explicit caps stop
                    # a compact model from rambling and reduce worst-case latency without keeping
                    # the model resident between requests.
                    "num_predict": 1_024 if deep_analysis else 512,
                },
            }
            async with httpx.AsyncClient(timeout=self.settings.ollama_timeout) as client:
                response = await client.post(
                    f"{self.settings.ollama_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
            self._warmed = self.settings.ollama_keep_alive not in {"0", "0s", "0m"}
        try:
            payload = response.json()
            message = payload.get("message", {}) if isinstance(payload, dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
        except ValueError:
            content = ""
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama devolvio una respuesta vacia")
        return content.strip()

    async def warmup(self) -> bool:
        """Optionally load the model, but only when the operator enabled it and RAM permits."""

        if not self.settings.ollama_warmup_enabled:
            return True
        available = self._available_memory_gb()
        if available is not None and available < self.settings.ollama_warmup_min_free_gb:
            return False
        async with self._model_lock:
            if self._warmed:
                return True
            return await self._warmup_unlocked()

    async def _warmup_unlocked(self) -> bool:
        payload = {
            "model": self.settings.ollama_model,
            "prompt": "Responde solamente: LISTO",
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {"temperature": 0, "num_predict": 2, "num_ctx": 512},
        }
        async with httpx.AsyncClient(timeout=self.settings.ollama_timeout) as client:
            response = await client.post(
                f"{self.settings.ollama_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
        self._warmed = self.settings.ollama_keep_alive not in {"0", "0s", "0m"}
        return True

    async def release(self) -> bool:
        """Unload this model if Ollama reports it resident; never load it just to unload it."""

        async with self._model_lock:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    running = await client.get(f"{self.settings.ollama_url}/api/ps")
                    running.raise_for_status()
                    models = running.json().get("models", [])
                    loaded = any(
                        isinstance(model, dict) and model.get("name") == self.settings.ollama_model
                        for model in models
                    )
                    if not loaded:
                        self._warmed = False
                        return True
                    response = await client.post(
                        f"{self.settings.ollama_url}/api/generate",
                        json={"model": self.settings.ollama_model, "keep_alive": 0},
                    )
                    response.raise_for_status()
                self._warmed = False
                return True
            except (httpx.HTTPError, AttributeError, TypeError, ValueError):
                return False


class FallbackBrain:
    """Small deterministic fallback so the UI remains testable without a model."""

    name = "fallback"

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            available=True,
            name="Nucleo de respaldo",
            detail="Conversacion limitada; Ollama no esta listo",
        )

    async def warmup(self) -> bool:
        return True

    async def release(self) -> bool:
        return True

    async def chat(self, messages: list[dict[str, str]]) -> str:
        text = messages[-1]["content"].strip()
        normalized = text.casefold()
        if any(word in normalized for word in ("hola", "buenas", "buenos dias")):
            return "Hola, Juan Diego. Aquí estoy, tranquilo y listo."
        if "quien eres" in normalized or "quién eres" in normalized:
            return (
                "Soy Jarvis, tu asistente local. De momento puedo escucharte y conversar contigo."
            )
        if "hora" in normalized:
            return f"Son las {datetime.now().strftime('%H:%M')}."
        if "estado" in normalized or "sistema" in normalized:
            return (
                "El nucleo esta funcionando. Para conversar sin limites falta iniciar Ollama "
                "y descargar el modelo configurado."
            )
        return (
            f"Te escuché decir: {text}. El núcleo conversacional local no está disponible ahora, "
            "pero sigo listo para tus acciones y comandos seguros."
        )

    async def chat_deep(self, messages: list[dict[str, str]]) -> str:
        return await self.chat(messages)


class AutoBrain:
    name = "auto"

    def __init__(self, settings: Settings) -> None:
        self.ollama = OllamaBrain(settings)
        self.fallback = FallbackBrain()
        self.active_name = self.fallback.name

    async def status(self) -> ProviderStatus:
        ollama_status = await self.ollama.status()
        if ollama_status.available:
            self.active_name = self.ollama.name
            return ollama_status
        self.active_name = self.fallback.name
        fallback_status = await self.fallback.status()
        fallback_status.detail = ollama_status.detail
        return fallback_status

    async def chat(self, messages: list[dict[str, str]]) -> str:
        try:
            self.active_name = self.ollama.name
            return await self.ollama.chat(messages)
        except (httpx.HTTPError, RuntimeError):
            pass
        self.active_name = self.fallback.name
        return await self.fallback.chat(messages)

    async def chat_deep(self, messages: list[dict[str, str]]) -> str:
        try:
            self.active_name = self.ollama.name
            return await self.ollama.chat_deep(messages)
        except (httpx.HTTPError, RuntimeError):
            pass
        self.active_name = self.fallback.name
        return await self.fallback.chat_deep(messages)

    async def warmup(self) -> bool:
        try:
            ready = await self.ollama.warmup()
            if not ready:
                self.active_name = self.fallback.name
                return False
            self.active_name = self.ollama.name
            return True
        except (httpx.HTTPError, RuntimeError):
            self.active_name = self.fallback.name
            return False

    async def release(self) -> bool:
        return await self.ollama.release()


def build_brain(settings: Settings) -> Brain:
    if settings.brain_mode == "fallback":
        return FallbackBrain()
    if settings.brain_mode == "ollama":
        return OllamaBrain(settings)
    return AutoBrain(settings)
