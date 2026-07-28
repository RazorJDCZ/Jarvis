from __future__ import annotations

from datetime import datetime
from typing import Protocol

import httpx

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


class Brain(Protocol):
    name: str

    async def status(self) -> ProviderStatus: ...

    async def chat(self, messages: list[dict[str, str]]) -> str: ...


class OllamaBrain:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
                    detail="Modelo local listo",
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
        payload = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.45,
                "top_p": 0.9,
                "repeat_penalty": 1.08,
                "num_ctx": 8192,
            },
        }
        async with httpx.AsyncClient(timeout=self.settings.ollama_timeout) as client:
            response = await client.post(
                f"{self.settings.ollama_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
        try:
            payload = response.json()
            message = payload.get("message", {}) if isinstance(payload, dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
        except ValueError:
            content = ""
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama devolvio una respuesta vacia")
        return content.strip()


class FallbackBrain:
    """Small deterministic fallback so the UI remains testable without a model."""

    name = "fallback"

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            available=True,
            name="Nucleo de respaldo",
            detail="Conversacion limitada; Ollama no esta listo",
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        text = messages[-1]["content"].strip()
        normalized = text.casefold()
        if any(word in normalized for word in ("hola", "buenas", "buenos dias")):
            return "Hola, Juandi. Aquí estoy, tranquilo y listo."
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
        ollama_status = await self.ollama.status()
        if ollama_status.available:
            self.active_name = self.ollama.name
            try:
                return await self.ollama.chat(messages)
            except (httpx.HTTPError, RuntimeError):
                pass
        self.active_name = self.fallback.name
        return await self.fallback.chat(messages)


def build_brain(settings: Settings) -> Brain:
    if settings.brain_mode == "fallback":
        return FallbackBrain()
    if settings.brain_mode == "ollama":
        return OllamaBrain(settings)
    return AutoBrain(settings)
