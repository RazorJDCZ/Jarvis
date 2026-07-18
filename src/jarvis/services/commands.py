from __future__ import annotations

import ctypes
import re
import subprocess  # nosec B404
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from jarvis import __version__
from jarvis.config import Settings


def normalize_command(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    collapsed = re.sub(r"\s+", " ", without_accents).strip()
    without_wake_prefix = re.sub(
        r"^(?:(?:oye|hey)\s+)?jarvis[,:;.!?\s]+",
        "",
        collapsed,
    )
    return without_wake_prefix.lstrip("¿¡ ")


class SafeAction(StrEnum):
    OPEN_CALCULATOR = "open_calculator"
    OPEN_NOTEPAD = "open_notepad"
    OPEN_EXPLORER = "open_explorer"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    VOLUME_MUTE = "volume_mute"


@dataclass(frozen=True, slots=True)
class ActionResult:
    success: bool
    detail: str = ""


class ActionExecutor(Protocol):
    def execute(self, action: SafeAction) -> ActionResult: ...


class WindowsSafeActionExecutor:
    """Executes only fixed, argument-free Windows actions from an enum."""

    _APPLICATIONS = {
        SafeAction.OPEN_CALCULATOR: "calc.exe",
        SafeAction.OPEN_NOTEPAD: "notepad.exe",
        SafeAction.OPEN_EXPLORER: "explorer.exe",
    }
    _MEDIA_KEYS = {
        SafeAction.VOLUME_MUTE: 0xAD,
        SafeAction.VOLUME_DOWN: 0xAE,
        SafeAction.VOLUME_UP: 0xAF,
    }
    _KEYEVENTF_KEYUP = 0x0002

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def execute(self, action: SafeAction) -> ActionResult:
        if not self.enabled:
            return ActionResult(False, "Las acciones seguras estan desactivadas")
        try:
            if action in self._APPLICATIONS:
                # The executable comes only from _APPLICATIONS; no user value or shell is used.
                subprocess.Popen(  # nosec B603
                    [self._APPLICATIONS[action]],
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                return ActionResult(True)
            if action in self._MEDIA_KEYS:
                virtual_key = self._MEDIA_KEYS[action]
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.keybd_event(virtual_key, 0, 0, 0)
                user32.keybd_event(virtual_key, 0, self._KEYEVENTF_KEYUP, 0)
                return ActionResult(True)
        except (OSError, AttributeError) as exc:
            return ActionResult(False, str(exc))
        return ActionResult(False, "Accion no reconocida")


@dataclass(frozen=True, slots=True)
class SafeCommandResult:
    response: str
    reset_history: bool = False


@dataclass(frozen=True, slots=True)
class _ActionCommand:
    patterns: tuple[str, ...]
    action: SafeAction
    success_response: str


class SafeCommandRouter:
    """Exact Spanish intent router. Unmatched text is delegated to the LLM."""

    _ACTION_COMMANDS = (
        _ActionCommand(
            (r"(?:abre|inicia|lanza) (?:la )?calculadora",),
            SafeAction.OPEN_CALCULATOR,
            "Abriendo la calculadora.",
        ),
        _ActionCommand(
            (r"(?:abre|inicia|lanza) (?:el )?(?:bloc de notas|notepad)",),
            SafeAction.OPEN_NOTEPAD,
            "Abriendo el bloc de notas.",
        ),
        _ActionCommand(
            (r"(?:abre|inicia|lanza) (?:el )?explorador(?: de archivos)?",),
            SafeAction.OPEN_EXPLORER,
            "Abriendo el explorador de archivos.",
        ),
        _ActionCommand(
            (r"(?:sube|aumenta) (?:el )?volumen", r"volumen (?:arriba|mas alto)"),
            SafeAction.VOLUME_UP,
            "He aumentado el volumen.",
        ),
        _ActionCommand(
            (r"(?:baja|reduce|disminuye) (?:el )?volumen", r"volumen (?:abajo|mas bajo)"),
            SafeAction.VOLUME_DOWN,
            "He reducido el volumen.",
        ),
        _ActionCommand(
            (
                r"(?:silencia|mutea) (?:el )?(?:audio|volumen|sonido)",
                r"(?:activa|desactiva|alterna) (?:el )?silencio",
            ),
            SafeAction.VOLUME_MUTE,
            "He alternado el silencio del sistema.",
        ),
    )
    _WEEKDAYS = (
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo",
    )
    _MONTHS = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )

    def __init__(
        self,
        settings: Settings,
        executor: ActionExecutor | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.executor = executor or WindowsSafeActionExecutor(settings.safe_actions_enabled)
        self._now = now or datetime.now

    @staticmethod
    def _matches(text: str, patterns: tuple[str, ...]) -> bool:
        optional_politeness = r"(?:por favor )?"
        suffix = r"(?: por favor)?[.!?]*"
        return any(
            re.fullmatch(optional_politeness + pattern + suffix, text) is not None
            for pattern in patterns
        )

    def try_handle(self, text: str) -> SafeCommandResult | None:
        command = normalize_command(text)
        if self._matches(command, (r"(?:que hora es|dime la hora|hora actual)",)):
            return SafeCommandResult(f"Son las {self._now().strftime('%H:%M')}.")
        if self._matches(
            command,
            (r"(?:que fecha es|que dia es hoy|dime la fecha|fecha actual)",),
        ):
            now = self._now()
            return SafeCommandResult(
                f"Hoy es {self._WEEKDAYS[now.weekday()]}, {now.day:02d} de "
                f"{self._MONTHS[now.month - 1]} de {now.year}."
            )
        if self._matches(command, (r"(?:que version eres|cual es tu version|version)",)):
            return SafeCommandResult(f"Estoy ejecutando Jarvis {__version__}, etapa uno.")
        if self._matches(
            command,
            (
                r"(?:que puedes hacer|ayuda|muestra (?:los )?comandos|lista (?:los )?comandos)",
            ),
        ):
            return SafeCommandResult(
                "Puedo conversar, decir la hora y la fecha, informar mi version, reiniciar "
                "la conversacion, abrir calculadora, bloc de notas o explorador, y controlar "
                "el volumen."
            )
        if self._matches(
            command,
            (r"(?:reinicia|borra|limpia) (?:la )?conversacion", r"olvida esta conversacion"),
        ):
            return SafeCommandResult(
                "He eliminado el contexto temporal de esta conversacion.",
                reset_history=True,
            )

        for action_command in self._ACTION_COMMANDS:
            if not self._matches(command, action_command.patterns):
                continue
            result = self.executor.execute(action_command.action)
            if result.success:
                return SafeCommandResult(action_command.success_response)
            return SafeCommandResult(
                f"No pude completar esa accion segura. {result.detail}".strip()
            )
        return None
