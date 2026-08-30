from __future__ import annotations

import asyncio
import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from jarvis.actions.browser import ControlledBrowser
from jarvis.actions.models import (
    ActionName,
    ActionPlan,
    ActionRisk,
    ActionSource,
    ExecutionResult,
    PreparedAction,
    PreparedWorkflow,
)
from jarvis.actions.vision import LocalVisionController
from jarvis.actions.windows import (
    AppController,
    AudioController,
    ClipboardController,
    DesktopInputController,
    PathController,
    SystemInfoController,
    WindowController,
)
from jarvis.capabilities.suite import CapabilitySuite
from jarvis.config import Settings


class ActionSecurityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActionSpec:
    risk: ActionRisk
    description: str


class ActionCatalog:
    session_aware = True
    _DIALOG_MONITORED = frozenset(
        {
            ActionName.APP_OPEN,
            ActionName.BROWSER_CLICK,
            ActionName.BROWSER_OPEN_RESULT,
            ActionName.PATH_OPEN,
            ActionName.POINTER_CLICK,
            ActionName.SCREEN_CLICK,
            ActionName.UI_CLICK,
            ActionName.UI_HOTKEY,
            ActionName.UI_KEY,
            ActionName.WINDOW_CLOSE,
        }
    )
    _APP_ALIASES = {
        "administrador de tareas": "task_manager",
        "ajustes": "settings",
        "bloc de notas": "notepad",
        "block de notas": "notepad",
        "calc": "calculator",
        "calculadora": "calculator",
        "calculator": "calculator",
        "chrome": "google chrome",
        "code": "visual studio code",
        "configuracion": "settings",
        "configuración": "settings",
        "explorador": "explorer",
        "explorador de archivos": "explorer",
        "epic games": "epic games launcher",
        "herramienta de recortes": "snipping_tool",
        "mapa de caracteres": "character_map",
        "minecraft": "minecraft launcher",
        "note pad": "notepad",
        "notepad": "notepad",
        "paint": "paint",
        "recortes": "snipping_tool",
        "riot": "riot client",
        "teams": "microsoft teams",
        "visual studio code": "visual studio code",
        "vscode": "visual studio code",
        "zoom": "zoom workplace",
    }
    _BROWSER_ALIASES = {
        "brave": "brave",
        "brave browser": "brave",
        "chrome": "chrome",
        "default": "default",
        "google chrome": "chrome",
        "edge": "edge",
        "microsoft edge": "edge",
        "navegador predeterminado": "default",
        "predeterminado": "default",
    }
    _BLOCKED_CONTROL_TERMS = (
        "borr",
        "compr",
        "confirmar pedido",
        "delete",
        "desinstal",
        "elimin",
        "enviar dinero",
        "format",
        "pagar",
        "pago",
        "purchase",
        "transfer",
    )
    _SPECS = {
        ActionName.APP_OPEN: ActionSpec(ActionRisk.LOW, "Abrir una aplicación permitida"),
        ActionName.APP_LIST: ActionSpec(ActionRisk.LOW, "Listar aplicaciones instaladas seguras"),
        ActionName.BROWSER_OPEN: ActionSpec(ActionRisk.LOW, "Abrir una página web segura"),
        ActionName.BROWSER_SEARCH: ActionSpec(ActionRisk.LOW, "Buscar información en la web"),
        ActionName.BROWSER_BACK: ActionSpec(ActionRisk.LOW, "Volver a la página anterior"),
        ActionName.BROWSER_FORWARD: ActionSpec(ActionRisk.LOW, "Avanzar en el navegador"),
        ActionName.BROWSER_REFRESH: ActionSpec(ActionRisk.LOW, "Recargar la página actual"),
        ActionName.BROWSER_NEW_TAB: ActionSpec(ActionRisk.LOW, "Abrir una pestaña nueva"),
        ActionName.BROWSER_LIST_TABS: ActionSpec(ActionRisk.LOW, "Listar las pestañas abiertas"),
        ActionName.BROWSER_SWITCH_TAB: ActionSpec(ActionRisk.LOW, "Cambiar de pestaña"),
        ActionName.BROWSER_CLOSE_TAB: ActionSpec(ActionRisk.MEDIUM, "Cerrar la pestaña actual"),
        ActionName.BROWSER_READ: ActionSpec(
            ActionRisk.LOW,
            "Leer el contenido visible de la página",
        ),
        ActionName.BROWSER_CLICK: ActionSpec(ActionRisk.MEDIUM, "Activar un elemento de la página"),
        ActionName.BROWSER_FILL: ActionSpec(ActionRisk.MEDIUM, "Escribir en un campo sin enviarlo"),
        ActionName.BROWSER_OPEN_RESULT: ActionSpec(
            ActionRisk.MEDIUM,
            "Abrir un resultado visible de la búsqueda",
        ),
        ActionName.VOLUME_SET: ActionSpec(ActionRisk.LOW, "Establecer el volumen del sistema"),
        ActionName.VOLUME_CHANGE: ActionSpec(ActionRisk.LOW, "Cambiar el volumen del sistema"),
        ActionName.VOLUME_MUTE: ActionSpec(ActionRisk.LOW, "Cambiar el silencio del sistema"),
        ActionName.VOLUME_GET: ActionSpec(ActionRisk.LOW, "Consultar el volumen del sistema"),
        ActionName.MEDIA_PLAY_PAUSE: ActionSpec(ActionRisk.LOW, "Reproducir o pausar multimedia"),
        ActionName.MEDIA_NEXT: ActionSpec(ActionRisk.LOW, "Pasar a la siguiente pista"),
        ActionName.MEDIA_PREVIOUS: ActionSpec(ActionRisk.LOW, "Volver a la pista anterior"),
        ActionName.MEDIA_STOP: ActionSpec(ActionRisk.LOW, "Detener la reproducción"),
        ActionName.WINDOW_LIST: ActionSpec(ActionRisk.LOW, "Listar las ventanas visibles"),
        ActionName.WINDOW_FOCUS: ActionSpec(ActionRisk.LOW, "Traer una ventana al frente"),
        ActionName.WINDOW_MINIMIZE: ActionSpec(ActionRisk.LOW, "Minimizar una ventana"),
        ActionName.WINDOW_MAXIMIZE: ActionSpec(ActionRisk.LOW, "Maximizar una ventana"),
        ActionName.WINDOW_RESTORE: ActionSpec(ActionRisk.LOW, "Restaurar una ventana"),
        ActionName.WINDOW_CLOSE: ActionSpec(
            ActionRisk.MEDIUM,
            "Solicitar el cierre de una ventana",
        ),
        ActionName.WINDOW_CURRENT: ActionSpec(ActionRisk.LOW, "Identificar la ventana activa"),
        ActionName.UI_INSPECT: ActionSpec(ActionRisk.LOW, "Inspeccionar controles accesibles"),
        ActionName.UI_CLICK: ActionSpec(ActionRisk.MEDIUM, "Activar un control de la ventana"),
        ActionName.UI_TYPE: ActionSpec(ActionRisk.MEDIUM, "Escribir en el control con foco"),
        ActionName.UI_HOTKEY: ActionSpec(ActionRisk.MEDIUM, "Enviar un atajo permitido"),
        ActionName.UI_KEY: ActionSpec(ActionRisk.MEDIUM, "Presionar una tecla permitida"),
        ActionName.POINTER_CLICK: ActionSpec(
            ActionRisk.HIGH,
            "Hacer clic en coordenadas de pantalla",
        ),
        ActionName.POINTER_SCROLL: ActionSpec(ActionRisk.MEDIUM, "Desplazar la vista activa"),
        ActionName.SCREENSHOT_TAKE: ActionSpec(
            ActionRisk.MEDIUM,
            "Guardar una captura local de las pantallas",
        ),
        ActionName.SCREEN_LIST: ActionSpec(
            ActionRisk.LOW,
            "Listar los monitores activos",
        ),
        ActionName.SCREEN_DESCRIBE: ActionSpec(
            ActionRisk.MEDIUM,
            "Analizar localmente lo visible en las pantallas",
        ),
        ActionName.SCREEN_ASK: ActionSpec(
            ActionRisk.MEDIUM,
            "Responder una pregunta usando la pantalla actual",
        ),
        ActionName.SCREEN_FIND: ActionSpec(
            ActionRisk.MEDIUM,
            "Localizar visualmente un elemento sin activarlo",
        ),
        ActionName.SCREEN_CLICK: ActionSpec(
            ActionRisk.HIGH,
            "Localizar y activar visualmente un elemento",
        ),
        ActionName.DESKTOP_SHOW: ActionSpec(ActionRisk.LOW, "Mostrar el escritorio"),
        ActionName.CLIPBOARD_READ: ActionSpec(ActionRisk.MEDIUM, "Leer texto del portapapeles"),
        ActionName.CLIPBOARD_WRITE: ActionSpec(
            ActionRisk.MEDIUM,
            "Copiar texto al portapapeles",
        ),
        ActionName.CLIPBOARD_ANALYZE: ActionSpec(
            ActionRisk.MEDIUM,
            "Analizar de forma ef\u00edmera el texto del portapapeles",
        ),
        ActionName.SYSTEM_STATUS: ActionSpec(ActionRisk.LOW, "Consultar recursos del sistema"),
        ActionName.PATH_OPEN: ActionSpec(ActionRisk.MEDIUM, "Abrir un archivo no ejecutable"),
        ActionName.PATH_OPEN_FOLDER: ActionSpec(ActionRisk.LOW, "Abrir una carpeta existente"),
        ActionName.SKILL_LIST: ActionSpec(ActionRisk.LOW, "Listar recetas seguras disponibles"),
        ActionName.SKILL_RUN: ActionSpec(ActionRisk.MEDIUM, "Ejecutar una receta declarativa"),
        ActionName.TASK_LIST: ActionSpec(
            ActionRisk.LOW, "Listar tareas de Appa o del almac\u00e9n local"
        ),
        ActionName.TASK_CREATE: ActionSpec(
            ActionRisk.MEDIUM, "Crear una tarea sin enviarla a terceros"
        ),
        ActionName.TASK_COMPLETE: ActionSpec(ActionRisk.MEDIUM, "Marcar una tarea como completada"),
        ActionName.PROJECT_LIST: ActionSpec(ActionRisk.LOW, "Listar proyectos de Appa"),
        ActionName.PROJECT_CREATE: ActionSpec(
            ActionRisk.MEDIUM, "Crear un proyecto en Appa"
        ),
        ActionName.CALENDAR_LIST: ActionSpec(ActionRisk.LOW, "Consultar la agenda de Appa"),
        ActionName.CALENDAR_CREATE: ActionSpec(
            ActionRisk.MEDIUM, "Crear un evento en el calendario de Appa"
        ),
        ActionName.INBOX_LIST: ActionSpec(ActionRisk.LOW, "Listar capturas del inbox de Appa"),
        ActionName.INBOX_CAPTURE: ActionSpec(
            ActionRisk.MEDIUM, "Guardar una captura en el inbox de Appa"
        ),
        ActionName.FOCUS_STATUS: ActionSpec(
            ActionRisk.LOW, "Consultar la sesi\u00f3n focus de Appa"
        ),
        ActionName.FOCUS_START: ActionSpec(
            ActionRisk.MEDIUM, "Iniciar una sesi\u00f3n focus en Appa"
        ),
        ActionName.APPA_BRIEFING: ActionSpec(
            ActionRisk.LOW, "Consultar el contexto personal unificado de Appa"
        ),
        ActionName.REMINDER_LIST: ActionSpec(ActionRisk.LOW, "Listar recordatorios activos"),
        ActionName.REMINDER_CREATE: ActionSpec(
            ActionRisk.MEDIUM, "Programar un recordatorio local"
        ),
        ActionName.REMINDER_CANCEL: ActionSpec(ActionRisk.MEDIUM, "Cancelar un recordatorio local"),
        ActionName.KNOWLEDGE_LIST: ActionSpec(
            ActionRisk.LOW, "Listar fuentes de la biblioteca local"
        ),
        ActionName.KNOWLEDGE_SEARCH: ActionSpec(
            ActionRisk.LOW, "Buscar con citas en la biblioteca local"
        ),
        ActionName.KNOWLEDGE_ADD_ATTACHMENT: ActionSpec(
            ActionRisk.MEDIUM,
            "Indexar un adjunto autorizado en la biblioteca local",
        ),
        ActionName.ATTACHMENT_LIST: ActionSpec(
            ActionRisk.LOW, "Listar adjuntos privados de la sesi\u00f3n"
        ),
        ActionName.PERMISSION_LIST: ActionSpec(ActionRisk.LOW, "Listar permisos recordados"),
        ActionName.PERMISSION_FORGET: ActionSpec(ActionRisk.MEDIUM, "Olvidar un permiso recordado"),
        ActionName.DEV_LIST: ActionSpec(
            ActionRisk.LOW, "Listar espacios de desarrollo autorizados"
        ),
        ActionName.DEV_INSPECT: ActionSpec(
            ActionRisk.LOW, "Inspeccionar un archivo de un workspace autorizado"
        ),
        ActionName.DEV_SEARCH: ActionSpec(
            ActionRisk.LOW, "Buscar texto en un workspace autorizado"
        ),
        ActionName.DEV_TEST: ActionSpec(
            ActionRisk.HIGH, "Ejecutar pruebas permitidas en un workspace autorizado"
        ),
        ActionName.GAME_LIST: ActionSpec(
            ActionRisk.LOW, "Listar juegos detectados en bibliotecas autorizadas"
        ),
        ActionName.GAME_LAUNCH: ActionSpec(ActionRisk.MEDIUM, "Abrir un juego instalado"),
    }
    _MODEL_READ_ONLY = frozenset(
        {
            ActionName.BROWSER_READ,
            ActionName.APP_LIST,
            ActionName.WINDOW_LIST,
            ActionName.WINDOW_CURRENT,
            ActionName.UI_INSPECT,
            ActionName.BROWSER_LIST_TABS,
            ActionName.SYSTEM_STATUS,
            ActionName.VOLUME_GET,
            ActionName.SCREEN_LIST,
            ActionName.SCREEN_DESCRIBE,
            ActionName.SCREEN_ASK,
            ActionName.SCREEN_FIND,
            ActionName.SKILL_LIST,
            ActionName.TASK_LIST,
            ActionName.PROJECT_LIST,
            ActionName.CALENDAR_LIST,
            ActionName.INBOX_LIST,
            ActionName.FOCUS_STATUS,
            ActionName.APPA_BRIEFING,
            ActionName.REMINDER_LIST,
            ActionName.KNOWLEDGE_LIST,
            ActionName.KNOWLEDGE_SEARCH,
            ActionName.ATTACHMENT_LIST,
            ActionName.PERMISSION_LIST,
            ActionName.DEV_LIST,
            ActionName.DEV_INSPECT,
            ActionName.DEV_SEARCH,
            ActionName.GAME_LIST,
        }
    )

    def __init__(
        self,
        data_dir: Path,
        search_url: str,
        settings: Settings | None = None,
        capabilities: CapabilitySuite | None = None,
    ) -> None:
        self.windows = WindowController()
        self.apps = AppController(self.windows)
        self.audio = AudioController()
        self.desktop = DesktopInputController()
        self.clipboard = ClipboardController()
        self.system = SystemInfoController()
        self.paths = PathController()
        self.browser = ControlledBrowser(
            data_dir,
            search_url,
            personal_profile=settings.browser_personal_profile if settings is not None else False,
            windows=self.windows,
        )
        self.vision = LocalVisionController(settings) if settings is not None else None
        self.capabilities = capabilities or (
            CapabilitySuite(settings, vision=self.vision)
            if settings is not None and settings.capabilities_enabled
            else None
        )
        self.screenshot_dir = data_dir / "screenshots" / "actions"

    @property
    def action_names(self) -> tuple[str, ...]:
        return tuple(action.value for action in self._SPECS)

    @staticmethod
    def _string(arguments: dict[str, Any], key: str, maximum: int) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ActionSecurityError(f"Falta un valor válido para {key}.")
        value = value.strip()
        if len(value) > maximum:
            raise ActionSecurityError(f"El valor {key} supera el límite permitido.")
        return value

    @staticmethod
    def _optional_string(
        arguments: dict[str, Any],
        key: str,
        maximum: int,
        *,
        allow_newlines: bool = False,
    ) -> str | None:
        value = arguments.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ActionSecurityError(f"El valor {key} no es válido.")
        value = value.strip()
        if not value:
            return None
        allowed = {"\n", "\t"} if allow_newlines else set()
        if len(value) > maximum or any(
            unicodedata.category(character) == "Cc" and character not in allowed
            for character in value
        ):
            raise ActionSecurityError(f"El valor {key} no es válido.")
        return value

    @classmethod
    def _required_safe_string(
        cls,
        arguments: dict[str, Any],
        key: str,
        maximum: int,
        *,
        allow_newlines: bool = False,
    ) -> str:
        value = cls._optional_string(
            arguments,
            key,
            maximum,
            allow_newlines=allow_newlines,
        )
        if value is None:
            raise ActionSecurityError(f"Falta un valor válido para {key}.")
        return value

    @staticmethod
    def _integer(
        arguments: dict[str, Any],
        key: str,
        minimum: int,
        maximum: int,
    ) -> int:
        value = arguments.get(key)
        if isinstance(value, bool):
            raise ActionSecurityError(f"El valor {key} no es numérico.")
        try:
            converted = int(value)
        except (TypeError, ValueError) as exc:
            raise ActionSecurityError(f"El valor {key} no es numérico.") from exc
        if not minimum <= converted <= maximum:
            raise ActionSecurityError(f"El valor {key} está fuera del rango permitido.")
        return converted

    @classmethod
    def _browser_argument(cls, arguments: dict[str, Any]) -> dict[str, str]:
        value = arguments.get("browser")
        if value is None:
            return {}
        if not isinstance(value, str) or not value.strip() or len(value) > 40:
            raise ActionSecurityError("El navegador solicitado no es válido.")
        browser = cls._BROWSER_ALIASES.get(value.strip().casefold())
        if browser is None:
            raise ActionSecurityError(
                "Solo puedo controlar Chrome, Edge o Brave mediante este canal seguro."
            )
        return {"browser": browser}

    @staticmethod
    def _monitor_argument(arguments: dict[str, Any]) -> dict[str, str]:
        value = arguments.get("monitor", "all")
        if not isinstance(value, str) or not value.strip() or len(value) > 60:
            raise ActionSecurityError("El monitor solicitado no es válido.")
        if any(character in value for character in "\r\n\t"):
            raise ActionSecurityError("El monitor solicitado no es válido.")
        return {"monitor": value.strip()}

    @staticmethod
    def _safe_url(value: str) -> str:
        if len(value) > 2_048 or any(character in value for character in "\r\n\t"):
            raise ActionSecurityError("La dirección web no es válida.")
        candidate = value.strip()
        if candidate.startswith("www.") or "://" not in candidate:
            candidate = "https://" + candidate
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ActionSecurityError("La dirección web contiene un puerto inválido.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ActionSecurityError("Solo se permiten páginas HTTP o HTTPS.")
        if port is not None and not 1 <= port <= 65_535:
            raise ActionSecurityError("La dirección web contiene un puerto inválido.")
        if parsed.username is not None or parsed.password is not None:
            raise ActionSecurityError("No se permiten credenciales dentro de la dirección web.")
        try:
            host = ipaddress.ip_address(parsed.hostname).compressed
        except ValueError:
            try:
                host = parsed.hostname.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ActionSecurityError("El dominio de la dirección web no es válido.") from exc
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc += f":{port}"
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment)
        )

    def prepare(self, plan: ActionPlan) -> PreparedAction:
        spec = self._SPECS.get(plan.name)
        if spec is None:
            raise ActionSecurityError("La acción no pertenece al catálogo permitido.")
        args = dict(plan.arguments)

        description = spec.description
        if plan.name is ActionName.APP_OPEN:
            app = self._string(args, "app", 80).casefold()
            for suffix in (" abierto", " abierta", " instalado", " instalada"):
                if app.endswith(suffix):
                    app = app[: -len(suffix)].strip()
                    break
            if app.startswith("el ") or app.startswith("la "):
                app = app[3:].strip()
            for prefix in (
                "aplicacion de ",
                "aplicación de ",
                "aplicacion ",
                "aplicación ",
                "app de ",
                "app ",
                "programa ",
            ):
                if app.startswith(prefix):
                    app = app[len(prefix) :].strip()
                    break
            app = self._APP_ALIASES.get(app, app)
            if app not in self.apps.allowed_apps:
                matches = self.apps.find_installed_apps(app)
                if not matches:
                    raise ActionSecurityError(
                        "No encontré una aplicación segura con ese nombre en el menú Inicio."
                    )
                if len(matches) > 1:
                    options = ", ".join(match.name for match in matches[:5])
                    raise ActionSecurityError(
                        f"Encontré varias aplicaciones: {options}. Indica el nombre completo."
                    )
                installed = matches[0]
                args = {
                    "app": app,
                    "app_id": installed.app_id,
                    "display_name": installed.name,
                    "target_path": installed.target_path,
                }
                description = f"Abrir la aplicación instalada {installed.name}"
            else:
                args = {"app": app}
        elif plan.name is ActionName.BROWSER_OPEN:
            args = {
                "url": self._safe_url(self._string(args, "url", 2_048)),
                **self._browser_argument(args),
            }
        elif plan.name is ActionName.BROWSER_SEARCH:
            args = {
                "query": self._string(args, "query", 500),
                **self._browser_argument(args),
            }
        elif plan.name is ActionName.BROWSER_NEW_TAB:
            args = self._browser_argument(args)
        elif plan.name in {ActionName.BROWSER_CLICK, ActionName.BROWSER_SWITCH_TAB}:
            args = {"target": self._string(args, "target", 200)}
        elif plan.name is ActionName.BROWSER_OPEN_RESULT:
            args = {"index": self._integer(args, "index", 1, 10)}
        elif plan.name is ActionName.BROWSER_FILL:
            args = {
                "field": self._string(args, "field", 120),
                "text": self._string(args, "text", 1_000),
            }
        elif plan.name is ActionName.VOLUME_SET:
            args = {"level": self._integer(args, "level", 0, 100)}
        elif plan.name is ActionName.VOLUME_CHANGE:
            step = self._integer(args, "step", -25, 25)
            if step == 0:
                raise ActionSecurityError("El cambio de volumen no puede ser cero.")
            args = {"step": step}
        elif plan.name is ActionName.VOLUME_MUTE:
            muted = args.get("muted")
            if not isinstance(muted, bool):
                raise ActionSecurityError("El estado de silencio no es válido.")
            args = {"muted": muted}
        elif plan.name in {
            ActionName.WINDOW_FOCUS,
            ActionName.WINDOW_MINIMIZE,
            ActionName.WINDOW_MAXIMIZE,
            ActionName.WINDOW_RESTORE,
            ActionName.WINDOW_CLOSE,
        }:
            title = args.get("title", "")
            if not isinstance(title, str) or len(title) > 200:
                raise ActionSecurityError("El título de ventana no es válido.")
            args = {"title": title.strip()}
        elif plan.name is ActionName.UI_CLICK:
            args = {"target": self._string(args, "target", 200)}
        elif plan.name is ActionName.UI_TYPE:
            args = {"text": self._string(args, "text", 1_000)}
        elif plan.name is ActionName.UI_HOTKEY:
            hotkey = self._string(args, "hotkey", 30)
            if hotkey not in {"copy", "paste", "undo", "redo", "save", "select_all"}:
                raise ActionSecurityError("Ese atajo no está permitido.")
            args = {"hotkey": hotkey}
        elif plan.name is ActionName.UI_KEY:
            key = self._string(args, "key", 30)
            if key not in {
                "enter",
                "escape",
                "tab",
                "shift_tab",
                "up",
                "down",
                "left",
                "right",
                "space",
                "backspace",
            }:
                raise ActionSecurityError("Esa tecla no está permitida.")
            args = {"key": key}
        elif plan.name is ActionName.POINTER_CLICK:
            args = {
                "x": self._integer(args, "x", -20_000, 20_000),
                "y": self._integer(args, "y", -20_000, 20_000),
            }
        elif plan.name is ActionName.POINTER_SCROLL:
            amount = self._integer(args, "amount", -50, 50)
            if amount == 0:
                raise ActionSecurityError("El desplazamiento no puede ser cero.")
            args = {"amount": amount}
        elif plan.name in {ActionName.PATH_OPEN, ActionName.PATH_OPEN_FOLDER}:
            args = {"path": self._string(args, "path", 1_024)}
        elif plan.name is ActionName.CLIPBOARD_WRITE:
            args = {"text": self._string(args, "text", 2_000)}
        elif plan.name is ActionName.CLIPBOARD_ANALYZE:
            operation = self._string(args, "operation", 40).casefold()
            if operation not in {"summarize", "explain", "correct", "translate"}:
                raise ActionSecurityError(
                    "El portapapeles solo puede resumirse, explicarse, corregirse o traducirse."
                )
            language = args.get("language")
            args = {"operation": operation}
            if isinstance(language, str) and language.strip():
                args["language"] = language.strip()[:40]
        elif plan.name is ActionName.SCREEN_DESCRIBE:
            args = self._monitor_argument(args)
            description = f"{description} en {args['monitor']}"
        elif plan.name is ActionName.SCREEN_ASK:
            args = {
                "question": self._string(args, "question", 800),
                **self._monitor_argument(args),
            }
            description = f"{description} en {args['monitor']}"
        elif plan.name in {ActionName.SCREEN_FIND, ActionName.SCREEN_CLICK}:
            args = {
                "target": self._string(args, "target", 300),
                **self._monitor_argument(args),
            }
            description = f"{description} en {args['monitor']}"
        elif plan.name is ActionName.SKILL_RUN:
            skill = self._string(args, "skill", 80).casefold()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,79}", skill):
                raise ActionSecurityError("El identificador de la receta no es v\u00e1lido.")
            raw_parameters = args.get("parameters", {})
            if not isinstance(raw_parameters, dict) or len(raw_parameters) > 12:
                raise ActionSecurityError("Los par\u00e1metros de la receta no son v\u00e1lidos.")
            args = {"skill": skill, "parameters": raw_parameters}
        elif plan.name is ActionName.TASK_CREATE:
            args = {
                "title": self._required_safe_string(args, "title", 300),
                "notes": self._optional_string(
                    args, "notes", 4_000, allow_newlines=True
                )
                or "",
            }
            due = self._optional_string(plan.arguments, "due", 120)
            if due is not None:
                args["due"] = due
            priority = self._optional_string(plan.arguments, "priority", 20)
            priority_aliases = {
                "low": "baja",
                "bajo": "baja",
                "normal": "media",
                "medium": "media",
                "high": "alta",
                "alto": "alta",
            }
            if priority is not None:
                priority = priority_aliases.get(priority.casefold(), priority.casefold())
                if priority not in {"baja", "media", "alta"}:
                    raise ActionSecurityError("La prioridad de la tarea no es válida.")
                args["priority"] = priority
            category = self._optional_string(plan.arguments, "category", 30)
            if category is not None:
                category = category.casefold()
                if category not in {
                    "universidad",
                    "personal",
                    "trabajo",
                    "finanzas",
                    "salud",
                    "otros",
                }:
                    raise ActionSecurityError("La categoría de la tarea no es válida.")
                args["category"] = category
            for key, maximum in (("reminder_at", 120), ("project_id", 128)):
                value = self._optional_string(plan.arguments, key, maximum)
                if value is not None:
                    args[key] = value
        elif plan.name is ActionName.TASK_COMPLETE:
            args = {"task": self._required_safe_string(args, "task", 300)}
        elif plan.name is ActionName.PROJECT_CREATE:
            args = {
                "name": self._required_safe_string(args, "name", 300),
                "description": self._optional_string(
                    args, "description", 4_000, allow_newlines=True
                )
                or "",
            }
            target_date = self._optional_string(plan.arguments, "target_date", 120)
            if target_date is not None:
                args["target_date"] = target_date
        elif plan.name is ActionName.CALENDAR_CREATE:
            args = {
                "title": self._required_safe_string(args, "title", 300),
                "start_at": self._required_safe_string(args, "start_at", 120),
                "description": self._optional_string(
                    args, "description", 4_000, allow_newlines=True
                )
                or "",
            }
            end_at = self._optional_string(plan.arguments, "end_at", 120)
            if end_at is not None:
                args["end_at"] = end_at
        elif plan.name is ActionName.INBOX_CAPTURE:
            args = {
                "text": self._required_safe_string(
                    args, "text", 4_000, allow_newlines=True
                ),
            }
        elif plan.name is ActionName.FOCUS_START:
            args = {"duration_minutes": self._integer(args, "duration_minutes", 5, 180)}
            for key, maximum in (("task_id", 128), ("task_title", 300)):
                value = self._optional_string(plan.arguments, key, maximum)
                if value is not None:
                    args[key] = value
        elif plan.name is ActionName.REMINDER_CREATE:
            recurrence = str(args.get("recurrence", "none")).strip().casefold()
            recurrence_aliases = {
                "ninguna": "none",
                "una vez": "none",
                "diario": "daily",
                "diaria": "daily",
                "cada dia": "daily",
                "semanal": "weekly",
                "cada semana": "weekly",
                "mensual": "monthly",
                "cada mes": "monthly",
            }
            recurrence = recurrence_aliases.get(recurrence, recurrence)
            if recurrence not in {"none", "daily", "weekly", "monthly"}:
                raise ActionSecurityError("La recurrencia del recordatorio no es v\u00e1lida.")
            args = {
                "title": self._string(args, "title", 300),
                "due": self._string(args, "due", 120),
                "recurrence": recurrence,
            }
        elif plan.name in {ActionName.REMINDER_CANCEL, ActionName.PERMISSION_FORGET}:
            key = "reminder" if plan.name is ActionName.REMINDER_CANCEL else "action"
            args = {key: self._string(args, key, 300)}
        elif plan.name is ActionName.KNOWLEDGE_SEARCH:
            args = {"query": self._string(args, "query", 500)}
        elif plan.name is ActionName.KNOWLEDGE_ADD_ATTACHMENT:
            args = {"attachment_id": self._string(args, "attachment_id", 64)}
            title = plan.arguments.get("title")
            if isinstance(title, str) and title.strip():
                args["title"] = title.strip()[:200]
        elif plan.name in {ActionName.DEV_INSPECT, ActionName.DEV_SEARCH, ActionName.DEV_TEST}:
            args = {"workspace": self._string(args, "workspace", 100).casefold()}
            if plan.name is ActionName.DEV_INSPECT:
                args["path"] = self._string(plan.arguments, "path", 500)
            elif plan.name is ActionName.DEV_SEARCH:
                args["query"] = self._string(plan.arguments, "query", 300)
        elif plan.name is ActionName.GAME_LAUNCH:
            args = {"game": self._string(args, "game", 200)}
        else:
            args = {}

        if plan.name in {ActionName.BROWSER_CLICK, ActionName.UI_CLICK, ActionName.SCREEN_CLICK}:
            normalized_target = args["target"].casefold()
            if any(term in normalized_target for term in self._BLOCKED_CONTROL_TERMS):
                raise ActionSecurityError(
                    "Ese control parece realizar una compra, transferencia o eliminación; "
                    "Jarvis no lo activará automáticamente."
                )

        risk = spec.risk
        if plan.name is ActionName.APP_OPEN and "app_id" in args:
            risk = ActionRisk.MEDIUM
        if (
            plan.source is ActionSource.LOCAL_MODEL
            and risk is ActionRisk.LOW
            and plan.name not in self._MODEL_READ_ONLY
        ):
            risk = ActionRisk.MEDIUM
        return PreparedAction(
            name=plan.name,
            arguments=args,
            risk=risk,
            description=description,
            source=plan.source,
        )

    async def execute(
        self,
        action: PreparedAction | PreparedWorkflow,
        session_id: str = "local",
    ) -> ExecutionResult:
        if isinstance(action, PreparedWorkflow):
            step_details: list[dict[str, Any]] = []
            last_message = ""
            for index, step in enumerate(action.steps, start=1):
                result = await self.execute(step, session_id=session_id)
                last_message = result.message.strip()[:1_500]
                step_details.append(
                    {
                        "step": index,
                        "action": step.name.value,
                        "success": result.success,
                        "message": last_message,
                    }
                )
                if result.details.get("dialog_confirmation_required") is True:
                    return ExecutionResult(
                        True,
                        result.message,
                        {
                            **result.details,
                            "steps": step_details,
                            "completed_steps": index,
                            "workflow_stopped_for_dialog": True,
                        },
                    )
                if not result.success:
                    return ExecutionResult(
                        False,
                        f"Detuve el flujo en el paso {index}: {result.message}",
                        {"steps": step_details, "completed_steps": index - 1},
                    )
            return ExecutionResult(
                True,
                (
                    f"Completé y verifiqué los {len(action.steps)} pasos solicitados. "
                    f"Resultado final: {last_message}"
                    if last_message
                    else f"Completé y verifiqué los {len(action.steps)} pasos solicitados."
                ),
                {
                    "steps": step_details,
                    "completed_steps": len(action.steps),
                    "final_result": last_message,
                },
            )
        baseline = (
            await asyncio.to_thread(self.windows.dialog_handles)
            if action.name in self._DIALOG_MONITORED
            else frozenset()
        )
        result = await self._execute_single(action, session_id=session_id)
        if action.name not in self._DIALOG_MONITORED or not result.success:
            return result
        dialog = await asyncio.to_thread(self.windows.wait_for_new_dialog, baseline)
        if dialog is None:
            return result
        return ExecutionResult(
            True,
            (
                f"{result.message} Apareció un diálogo que necesita una decisión explícita."
                if result.message
                else "Apareció un diálogo que necesita una decisión explícita."
            ),
            {
                **result.details,
                "dialog_confirmation_required": True,
                "dialog": dialog.as_dict(),
                "trigger_succeeded": result.success,
            },
        )

    async def _execute_single(
        self,
        action: PreparedAction,
        session_id: str = "local",
    ) -> ExecutionResult:
        name = action.name
        args = action.arguments
        if name is ActionName.APP_OPEN:
            return await asyncio.to_thread(
                self.apps.open,
                args["app"],
                "",
                args.get("app_id", ""),
                args.get("display_name", ""),
                args.get("target_path", ""),
            )
        if name is ActionName.APP_LIST:
            return await asyncio.to_thread(self.apps.list_installed)
        if name is ActionName.BROWSER_OPEN:
            return await self.browser.open(args["url"], args.get("browser"))
        if name is ActionName.BROWSER_SEARCH:
            return await self.browser.search(args["query"], args.get("browser"))
        if name in {
            ActionName.BROWSER_BACK,
            ActionName.BROWSER_FORWARD,
            ActionName.BROWSER_REFRESH,
        }:
            direction = name.value.split(".", maxsplit=1)[1]
            return await self.browser.navigate(direction)
        if name is ActionName.BROWSER_NEW_TAB:
            return await self.browser.new_tab(args.get("browser"))
        if name is ActionName.BROWSER_LIST_TABS:
            return await self.browser.list_tabs()
        if name is ActionName.BROWSER_SWITCH_TAB:
            return await self.browser.switch_tab(args["target"])
        if name is ActionName.BROWSER_CLOSE_TAB:
            return await self.browser.close_tab()
        if name is ActionName.BROWSER_READ:
            return await self.browser.read()
        if name is ActionName.BROWSER_CLICK:
            return await self.browser.click(args["target"])
        if name is ActionName.BROWSER_FILL:
            return await self.browser.fill(args["field"], args["text"])
        if name is ActionName.BROWSER_OPEN_RESULT:
            return await self.browser.open_result(args["index"])
        if name is ActionName.VOLUME_SET:
            return await asyncio.to_thread(self.audio.set_level, args["level"])
        if name is ActionName.VOLUME_CHANGE:
            return await asyncio.to_thread(self.audio.change_level, args["step"])
        if name is ActionName.VOLUME_MUTE:
            return await asyncio.to_thread(self.audio.mute, args["muted"])
        if name is ActionName.VOLUME_GET:
            return await asyncio.to_thread(self.audio.get_level)
        if name in {
            ActionName.MEDIA_PLAY_PAUSE,
            ActionName.MEDIA_NEXT,
            ActionName.MEDIA_PREVIOUS,
            ActionName.MEDIA_STOP,
        }:
            key_name = name.value.split(".", maxsplit=1)[1]
            return await asyncio.to_thread(self.audio.media_key, key_name)
        if name is ActionName.WINDOW_LIST:
            return await asyncio.to_thread(self.windows.list_windows)
        if name is ActionName.WINDOW_CURRENT:
            return await asyncio.to_thread(self.windows.current)
        if name is ActionName.WINDOW_FOCUS:
            return await asyncio.to_thread(self.windows.focus, args["title"])
        if name in {
            ActionName.WINDOW_MINIMIZE,
            ActionName.WINDOW_MAXIMIZE,
            ActionName.WINDOW_RESTORE,
        }:
            operation = name.value.split(".", maxsplit=1)[1]
            return await asyncio.to_thread(self.windows.change_state, operation, args["title"])
        if name is ActionName.WINDOW_CLOSE:
            return await asyncio.to_thread(self.windows.close, args["title"])
        if name is ActionName.UI_INSPECT:
            return await asyncio.to_thread(self.windows.inspect_controls)
        if name is ActionName.UI_CLICK:
            return await asyncio.to_thread(self.windows.click_control, args["target"])
        if name is ActionName.UI_TYPE:
            return await asyncio.to_thread(self.windows.type_text, args["text"])
        if name is ActionName.UI_HOTKEY:
            return await asyncio.to_thread(self.windows.send_hotkey, args["hotkey"])
        if name is ActionName.UI_KEY:
            return await asyncio.to_thread(self.windows.press_key, args["key"])
        if name is ActionName.POINTER_CLICK:
            if action.source is ActionSource.CONFIRMATION:
                return await asyncio.to_thread(
                    self.desktop.click_if_cursor_unchanged,
                    args["x"],
                    args["y"],
                )
            return await asyncio.to_thread(self.desktop.click, args["x"], args["y"])
        if name is ActionName.POINTER_SCROLL:
            return await asyncio.to_thread(self.desktop.scroll, args["amount"])
        if name is ActionName.SCREENSHOT_TAKE:
            return await asyncio.to_thread(self.desktop.screenshot, self.screenshot_dir)
        if name is ActionName.SCREEN_LIST:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await asyncio.to_thread(self.vision.list_monitors)
        if name is ActionName.SCREEN_DESCRIBE:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.describe(args["monitor"])
        if name is ActionName.SCREEN_ASK:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.ask(args["question"], args["monitor"])
        if name is ActionName.SCREEN_FIND:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.find(args["target"], args["monitor"])
        if name is ActionName.SCREEN_CLICK:
            if args["monitor"] == "all":
                accessible = await asyncio.to_thread(self.windows.click_control, args["target"])
                if accessible.success:
                    return ExecutionResult(
                        True,
                        f"{accessible.message} Usé el árbol accesible de Windows.",
                        {
                            "method": "accessibility",
                            "verified": True,
                            "monitor": "all",
                            "monitor_label": "Ventana activa",
                        },
                    )
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            located = await self.vision.find(args["target"], args["monitor"])
            if not located.success:
                return located
            if located.details.get("dangerous") is True:
                return ExecutionResult(
                    False,
                    "La visión detectó que el elemento podría ser destructivo o financiero.",
                )
            moved = await asyncio.to_thread(
                self.desktop.move,
                located.details["x"],
                located.details["y"],
            )
            return ExecutionResult(
                moved.success,
                (
                    f"{moved.message} Objetivo visual estimado: "
                    f"{located.details['element']}. Revisa la posición antes de confirmar el clic."
                    if moved.success
                    else moved.message
                ),
                {
                    **located.details,
                    "method": "local-vision",
                    "cursor_moved": moved.success,
                    "pixel_confirmation_required": moved.success,
                },
            )
        if name is ActionName.DESKTOP_SHOW:
            return await asyncio.to_thread(self.desktop.show_desktop)
        if name is ActionName.CLIPBOARD_READ:
            return await asyncio.to_thread(self.clipboard.read)
        if name is ActionName.CLIPBOARD_WRITE:
            return await asyncio.to_thread(self.clipboard.write, args["text"])
        if name is ActionName.SYSTEM_STATUS:
            if self.capabilities is not None:
                return await self.capabilities.execute(
                    session_id,
                    name,
                    args,
                    clipboard=self.clipboard,
                    catalog=self,
                )
            return await asyncio.to_thread(self.system.status)
        if name is ActionName.PATH_OPEN:
            return await asyncio.to_thread(self.paths.open_file, args["path"])
        if name is ActionName.PATH_OPEN_FOLDER:
            return await asyncio.to_thread(self.paths.open_folder, args["path"])
        if name in {
            ActionName.CLIPBOARD_ANALYZE,
            ActionName.SKILL_LIST,
            ActionName.SKILL_RUN,
            ActionName.TASK_LIST,
            ActionName.TASK_CREATE,
            ActionName.TASK_COMPLETE,
            ActionName.PROJECT_LIST,
            ActionName.PROJECT_CREATE,
            ActionName.CALENDAR_LIST,
            ActionName.CALENDAR_CREATE,
            ActionName.INBOX_LIST,
            ActionName.INBOX_CAPTURE,
            ActionName.FOCUS_STATUS,
            ActionName.FOCUS_START,
            ActionName.APPA_BRIEFING,
            ActionName.REMINDER_LIST,
            ActionName.REMINDER_CREATE,
            ActionName.REMINDER_CANCEL,
            ActionName.KNOWLEDGE_LIST,
            ActionName.KNOWLEDGE_SEARCH,
            ActionName.KNOWLEDGE_ADD_ATTACHMENT,
            ActionName.ATTACHMENT_LIST,
            ActionName.PERMISSION_LIST,
            ActionName.PERMISSION_FORGET,
            ActionName.DEV_LIST,
            ActionName.DEV_INSPECT,
            ActionName.DEV_SEARCH,
            ActionName.DEV_TEST,
            ActionName.GAME_LIST,
            ActionName.GAME_LAUNCH,
        }:
            if self.capabilities is None:
                return ExecutionResult(
                    False, "Las capacidades ampliadas no est\u00e1n configuradas."
                )
            return await self.capabilities.execute(
                session_id,
                name,
                args,
                clipboard=self.clipboard,
                catalog=self,
            )
        return ExecutionResult(False, "La acción no tiene un ejecutor disponible.")

    async def choose_dialog_option(
        self,
        parent_handle: int,
        dialog_handle: int,
        choice: str,
    ) -> ExecutionResult:
        baseline = await asyncio.to_thread(self.windows.dialog_handles)
        result = await asyncio.to_thread(
            self.windows.choose_dialog_option,
            parent_handle,
            dialog_handle,
            choice,
        )
        if not result.success:
            return result
        dialog = await asyncio.to_thread(self.windows.wait_for_new_dialog, baseline)
        if dialog is None:
            return result
        return ExecutionResult(
            True,
            f"{result.message} Apareció otro diálogo que también necesita tu decisión.",
            {
                **result.details,
                "dialog_confirmation_required": True,
                "dialog": dialog.as_dict(),
            },
        )

    async def dialog_available(self, parent_handle: int, dialog_handle: int) -> bool:
        dialogs = await asyncio.to_thread(self.windows.dialogs)
        return any(
            dialog.parent_handle == parent_handle and dialog.dialog_handle == dialog_handle
            for dialog in dialogs
        )

    async def close(self) -> None:
        if self.capabilities is not None:
            await self.capabilities.close()
        await self.browser.close()
