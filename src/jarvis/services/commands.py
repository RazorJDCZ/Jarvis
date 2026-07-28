from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from jarvis import __version__
from jarvis.actions.parser import normalize_request


def normalize_command(text: str) -> str:
    return normalize_request(text)


@dataclass(frozen=True, slots=True)
class SafeCommandResult:
    response: str
    reset_history: bool = False


class SafeCommandRouter:
    """Handles information-only commands without consulting the model."""

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

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
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
            return SafeCommandResult(f"Estoy ejecutando Jarvis {__version__}, etapa cuatro.")
        if self._matches(
            command,
            (r"(?:que puedes hacer|ayuda|muestra (?:los )?comandos|lista (?:los )?comandos)",),
        ):
            return SafeCommandResult(
                "Puedo conversar, abrir las aplicaciones seguras publicadas por Windows y "
                "controlar páginas en Chrome, Edge o Brave. También manejo volumen, multimedia, "
                "ventanas y controles accesibles, puedo describir la pantalla y encadenar hasta "
                "tres pasos explícitos. Tengo memoria local para tus preferencias, proyectos y "
                "conversaciones recientes. Di ‘qué recuerdas de mí’ para consultarla o ‘recuerda "
                "que...’ para guardar algo. Di ‘qué aplicaciones puedes abrir’ para ver el "
                "inventario. "
                "Las acciones sensibles "
                "siempre piden confirmación y los diálogos emergentes esperan una opción concreta. "
                "Si hablo demasiado, di ‘Jarvis, es suficiente’."
            )
        if self._matches(
            command,
            (r"(?:reinicia|borra|limpia) (?:la )?conversacion", r"olvida esta conversacion"),
        ):
            return SafeCommandResult(
                "He eliminado el contexto temporal y las acciones pendientes de esta conversación.",
                reset_history=True,
            )
        return None
