from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "si", "sí"}


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    host: str = os.getenv("JARVIS_HOST", "127.0.0.1")
    port: int = _env_int("JARVIS_PORT", 8765)

    brain_mode: str = os.getenv("JARVIS_BRAIN_MODE", "auto").lower()
    ollama_url: str = os.getenv("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("JARVIS_OLLAMA_MODEL", "qwen3.5:4b")
    ollama_timeout: float = _env_float("JARVIS_OLLAMA_TIMEOUT", 180.0)

    stt_model: str = os.getenv("JARVIS_STT_MODEL", "small")
    stt_device: str = os.getenv("JARVIS_STT_DEVICE", "cpu")
    stt_compute_type: str = os.getenv("JARVIS_STT_COMPUTE_TYPE", "int8")
    stt_language: str = os.getenv("JARVIS_STT_LANGUAGE", "es")

    wake_word: str = os.getenv("JARVIS_WAKE_WORD", "jarvis")
    wake_window_seconds: int = _env_int("JARVIS_WAKE_WINDOW_SECONDS", 10)
    max_history_messages: int = _env_int("JARVIS_MAX_HISTORY_MESSAGES", 16)
    max_sessions: int = _env_int("JARVIS_MAX_SESSIONS", 64)
    safe_actions_enabled: bool = _env_bool("JARVIS_SAFE_ACTIONS_ENABLED", True)
    max_audio_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "La etapa 1 solo puede escuchar en loopback (127.0.0.1, localhost o ::1)"
            )

    @property
    def data_dir(self) -> Path:
        return self.project_root / ".data"

    @property
    def stt_model_reference(self) -> str:
        configured = Path(self.stt_model)
        if configured.is_absolute() and configured.exists():
            return str(configured)
        project_relative = self.project_root / configured
        if project_relative.exists():
            return str(project_relative)
        bundled = self.project_root / "models" / "whisper" / self.stt_model
        return str(bundled) if bundled.exists() else self.stt_model

    @property
    def piper_model(self) -> Path:
        configured = Path(
            os.getenv(
                "JARVIS_PIPER_MODEL",
                "models/piper/es_ES-sharvard-medium.onnx",
            )
        )
        return configured if configured.is_absolute() else self.project_root / configured

    @property
    def web_dir(self) -> Path:
        return Path(__file__).resolve().parent / "web"


SYSTEM_PROMPT = """\
Eres JARVIS, un asistente personal privado que vive en la computadora de Juandi.
Hablas principalmente en espanol y puedes cambiar de idioma si el usuario lo hace.
Tu personalidad es serena, ingeniosa, leal y precisa. Responde de forma natural y breve,
normalmente en una a tres oraciones, porque tus respuestas se leen en voz alta. Solo amplia una
respuesta cuando el usuario lo pida o el tema realmente lo requiera. No finjas haber realizado
acciones. Algunas ordenes locales sencillas se ejecutan mediante una lista blanca fuera del
modelo; para cualquier otra accion sobre la computadora explica brevemente que esa capacidad se
habilitara en la etapa del motor de acciones.
No reveles razonamientos internos. Cuando no sepas algo, dilo con honestidad.
"""
