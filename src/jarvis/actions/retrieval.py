from __future__ import annotations

import re
import unicodedata
from collections import Counter
from math import log


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _features(value: str) -> Counter[str]:
    words = _normalize(value).split()
    result: Counter[str] = Counter(words)
    for left, right in zip(words, words[1:], strict=False):
        result[f"{left}_{right}"] += 2
    compact = "".join(words)
    for index in range(max(0, len(compact) - 3)):
        result[f"#{compact[index : index + 4]}"] += 0.12
    return result


class CapabilityRetriever:
    """Select a small relevant tool set without trusting the model with the full catalog."""

    # Ranking tools and deciding whether tools are needed are different problems.
    # Function words, fuzzy character matches and calendar pinning ("hoy", "dia")
    # are useful for retrieval but must not turn ordinary speech into an action.
    _ADMISSION_STOPWORDS = frozenset(
        "a al algo algun alguna algunos algunas ante asi aun aunque buen buenos como con "  # noqa: SIM905
        "cual cuando de del desde donde el ella ellas ellos en entre era es esa esas ese esos "
        "esta estas este esto estos estoy ha hace hacia hasta hay hola hoy jarvis la las le "
        "les lo los mas me mi mis mucho muy nada ni no nos o otra otro para pero poco por "
        "porque que quien se si sin sobre su sus te tengo ti tiene todo tu tus un una uno "
        "unos unas va vas vez ya y yo the a an to of is are how you your i my please".split()
    )

    _DOMAIN_HINTS = {
        "app.": "aplicacion programa software instalado abrir ejecutar lanzar",
        "browser.": "navegador chrome edge brave web pagina sitio internet google buscar pestaña",
        "volume.": "volumen audio sonido silencio mute escuchar porcentaje",
        "media.": "musica video reproduccion cancion pista pausar continuar",
        "window.": "ventana programa abierto primer plano minimizar maximizar cerrar foco",
        "ui.": "interfaz boton campo control escribir presionar seleccionar accesibilidad",
        "pointer.": "cursor mouse desplazamiento scroll coordenada",
        "screen.": "monitor pantalla visible ver captura imagen localizar elemento",
        "screenshot.": "captura pantalla guardar imagen screenshot",
        "desktop.": "escritorio windows mostrar",
        "clipboard.": "portapapeles copiar pegar texto resumir analizar",
        "system.": "computadora pc sistema cpu ram memoria disco temperatura recursos estado",
        "path.": "archivo carpeta ruta abrir explorador documento",
        "skill.": "receta skill automatizacion capacidad",
        "task.": "tarea pendiente deber recordatorio productividad appa completar crear listar",
        "project.": "proyecto appa objetivo avance plan",
        "calendar.": "agenda calendario evento cita reunion clase horario appa",
        "inbox.": "inbox idea captura anotar bandeja appa",
        "focus.": "focus concentracion pomodoro estudiar sesion appa",
        "appa.": (
            "appa resumen dia productividad agenda tareas proyectos inbox focus prioridad "
            "planificar"
        ),
        "mail.": "correo gmail email buscar remitente asunto responder enviar borrador autorizado",
        "google_calendar.": "google calendar agenda evento editar reprogramar cambiar fecha hora",
        "reminder.": "recordatorio aviso alarma recordar programar",
        "knowledge.": "biblioteca conocimiento documento buscar fuente cita privado",
        "attachment.": "adjunto archivo cargado sesion",
        "permission.": "permiso autorizacion recordar olvidar seguridad",
        "dev.": (
            "codigo programar desarrollo codex workspace repositorio pruebas archivo buscar "
            "crear carpeta proyecto implementar corregir"
        ),
        "game.": "juego videojuego steam epic jugar biblioteca",
    }

    _PINNED_GROUPS = {
        "abiert*": ("window.list", "window.current", "app.open", "app.list"),
        "monitor": ("screen.list", "screen.describe", "screen.ask", "window.list"),
        "pantalla": ("screen.describe", "screen.ask", "screen.find", "screen.list"),
        "appa": (
            "appa.briefing",
            "task.list",
            "task.create",
            "project.list",
            "calendar.list",
            "inbox.capture",
            "focus.status",
        ),
        "hoy": ("appa.briefing", "task.list", "calendar.list", "reminder.list"),
        "dia": ("appa.briefing", "task.list", "calendar.list"),
        "volumen": ("volume.get", "volume.set", "volume.change", "volume.mute"),
        "sonido": ("volume.get", "volume.set", "volume.change", "volume.mute"),
        "correo": ("mail.search", "mail.reply", "browser.open", "browser.read"),
        "gmail": ("mail.search", "mail.reply", "browser.open"),
        "codex": ("dev.codex_task", "dev.list", "dev.create_project"),
        "carpeta": ("dev.create_folder", "path.open_folder", "dev.list"),
        "encuentra": ("screen.find", "ui.inspect", "browser.read", "browser.search"),
        "recu*": ("reminder.create", "reminder.list", "calendar.create", "task.create"),
    }

    def __init__(self, action_names: tuple[str, ...], descriptions: dict[str, str]) -> None:
        self.action_names = tuple(action_names)
        self._documents: dict[str, Counter[str]] = {}
        for name in self.action_names:
            prefix = name.split(".", maxsplit=1)[0] + "."
            document = f"{name} {descriptions.get(name, '')} {self._DOMAIN_HINTS.get(prefix, '')}"
            self._documents[name] = _features(document)
        document_frequency: Counter[str] = Counter()
        for document in self._documents.values():
            document_frequency.update(document.keys())
        total = max(1, len(self._documents))
        self._idf = {
            feature: log((total + 1) / (frequency + 1)) + 1
            for feature, frequency in document_frequency.items()
        }

    @staticmethod
    def _marker_present(marker: str, normalized: str) -> bool:
        words = normalized.split()
        if marker.endswith("*"):
            stem = marker[:-1]
            return bool(stem) and any(word.startswith(stem) for word in words)
        if " " in marker:
            return f" {marker} " in f" {normalized} "
        return marker in words

    def ranked(self, request: str) -> tuple[tuple[str, float], ...]:
        query = _features(request)
        normalized = _normalize(request)
        score_by_name: dict[str, float] = {}
        for name, document in self._documents.items():
            overlap = sum(
                min(weight, document.get(feature, 0)) * self._idf.get(feature, 1.0)
                for feature, weight in query.items()
            )
            domain = name.split(".", maxsplit=1)[0]
            if domain in normalized.split():
                overlap += 4
            score_by_name[name] = float(overlap)
        for marker, pinned in self._PINNED_GROUPS.items():
            if self._marker_present(marker, normalized):
                for name in pinned:
                    if name in score_by_name:
                        score_by_name[name] += 6
        if (
            re.search(r"(?:https?://|www\.)\S+", request, flags=re.IGNORECASE)
            and "browser.open" in score_by_name
        ):
            score_by_name["browser.open"] += 12
        scores = sorted(score_by_name.items(), key=lambda item: (-item[1], item[0]))
        return tuple(scores)

    def admission_score(self, request: str) -> float:
        """Require meaningful whole-word evidence before speculative tool planning."""
        query = {
            feature: weight
            for feature, weight in _features(request).items()
            if not feature.startswith("#")
            and any(word not in self._ADMISSION_STOPWORDS for word in feature.split("_"))
        }
        return max(
            (
                sum(
                    min(weight, document.get(feature, 0)) * self._idf.get(feature, 1.0)
                    for feature, weight in query.items()
                )
                for document in self._documents.values()
            ),
            default=0.0,
        )

    def select(self, request: str, *, limit: int = 18) -> tuple[str, ...]:
        safe_limit = max(8, min(limit, len(self.action_names)))
        selected = [name for name, _ in self.ranked(request)]
        unique: list[str] = []
        for name in selected:
            if name in self._documents and name not in unique:
                unique.append(name)
            if len(unique) >= safe_limit:
                break
        return tuple(unique)
