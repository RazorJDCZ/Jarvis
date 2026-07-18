from __future__ import annotations

import asyncio
import ipaddress
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
from jarvis.config import Settings


class ActionSecurityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActionSpec:
    risk: ActionRisk
    description: str


class ActionCatalog:
    _APP_ALIASES = {
        "administrador de tareas": "task_manager",
        "ajustes": "settings",
        "bloc de notas": "notepad",
        "block de notas": "notepad",
        "calc": "calculator",
        "calculadora": "calculator",
        "calculator": "calculator",
        "configuracion": "settings",
        "configuración": "settings",
        "explorador": "explorer",
        "explorador de archivos": "explorer",
        "herramienta de recortes": "snipping_tool",
        "mapa de caracteres": "character_map",
        "note pad": "notepad",
        "notepad": "notepad",
        "paint": "paint",
        "recortes": "snipping_tool",
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
        ActionName.SYSTEM_STATUS: ActionSpec(ActionRisk.LOW, "Consultar recursos del sistema"),
        ActionName.PATH_OPEN: ActionSpec(ActionRisk.MEDIUM, "Abrir un archivo no ejecutable"),
        ActionName.PATH_OPEN_FOLDER: ActionSpec(ActionRisk.LOW, "Abrir una carpeta existente"),
    }
    _MODEL_READ_ONLY = frozenset(
        {
            ActionName.BROWSER_READ,
            ActionName.WINDOW_LIST,
            ActionName.WINDOW_CURRENT,
            ActionName.UI_INSPECT,
            ActionName.BROWSER_LIST_TABS,
            ActionName.SYSTEM_STATUS,
            ActionName.VOLUME_GET,
        }
    )

    def __init__(
        self,
        data_dir: Path,
        search_url: str,
        settings: Settings | None = None,
    ) -> None:
        self.windows = WindowController()
        self.apps = AppController(self.windows)
        self.audio = AudioController()
        self.desktop = DesktopInputController()
        self.clipboard = ClipboardController()
        self.system = SystemInfoController()
        self.paths = PathController()
        self.browser = ControlledBrowser(data_dir, search_url)
        self.vision = LocalVisionController(settings) if settings is not None else None
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
            app = self._APP_ALIASES.get(app, app)
            if app not in self.apps.allowed_apps:
                shortcut = self.apps.resolve_shortcut(app)
                if shortcut is None:
                    raise ActionSecurityError(
                        "No encontré esa aplicación en la lista blanca ni en el menú Inicio."
                    )
                args = {"app": app, "shortcut": str(shortcut)}
                description = f"Abrir la aplicación instalada {shortcut.stem}"
            else:
                args = {"app": app}
        elif plan.name is ActionName.BROWSER_OPEN:
            args = {"url": self._safe_url(self._string(args, "url", 2_048))}
        elif plan.name is ActionName.BROWSER_SEARCH:
            args = {"query": self._string(args, "query", 500)}
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
        elif plan.name is ActionName.SCREEN_ASK:
            args = {"question": self._string(args, "question", 800)}
        elif plan.name in {ActionName.SCREEN_FIND, ActionName.SCREEN_CLICK}:
            args = {"target": self._string(args, "target", 300)}
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
        if plan.name is ActionName.APP_OPEN and "shortcut" in args:
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

    async def execute(self, action: PreparedAction | PreparedWorkflow) -> ExecutionResult:
        if isinstance(action, PreparedWorkflow):
            step_details: list[dict[str, Any]] = []
            for index, step in enumerate(action.steps, start=1):
                result = await self.execute(step)
                step_details.append(
                    {"step": index, "action": step.name.value, "success": result.success}
                )
                if not result.success:
                    return ExecutionResult(
                        False,
                        f"Detuve el flujo en el paso {index}: {result.message}",
                        {"steps": step_details, "completed_steps": index - 1},
                    )
            return ExecutionResult(
                True,
                f"Completé y verifiqué los {len(action.steps)} pasos solicitados.",
                {"steps": step_details, "completed_steps": len(action.steps)},
            )
        name = action.name
        args = action.arguments
        if name is ActionName.APP_OPEN:
            return await asyncio.to_thread(
                self.apps.open,
                args["app"],
                args.get("shortcut", ""),
            )
        if name is ActionName.BROWSER_OPEN:
            return await self.browser.open(args["url"])
        if name is ActionName.BROWSER_SEARCH:
            return await self.browser.search(args["query"])
        if name in {
            ActionName.BROWSER_BACK,
            ActionName.BROWSER_FORWARD,
            ActionName.BROWSER_REFRESH,
        }:
            direction = name.value.split(".", maxsplit=1)[1]
            return await self.browser.navigate(direction)
        if name is ActionName.BROWSER_NEW_TAB:
            return await self.browser.new_tab()
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
        if name is ActionName.SCREEN_DESCRIBE:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.describe()
        if name is ActionName.SCREEN_ASK:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.ask(args["question"])
        if name is ActionName.SCREEN_FIND:
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            return await self.vision.find(args["target"])
        if name is ActionName.SCREEN_CLICK:
            accessible = await asyncio.to_thread(self.windows.click_control, args["target"])
            if accessible.success:
                return ExecutionResult(
                    True,
                    f"{accessible.message} Usé el árbol accesible de Windows.",
                    {"method": "accessibility", "verified": True},
                )
            if self.vision is None:
                return ExecutionResult(False, "La visión local no está configurada.")
            located = await self.vision.find(args["target"])
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
            return await asyncio.to_thread(self.system.status)
        if name is ActionName.PATH_OPEN:
            return await asyncio.to_thread(self.paths.open_file, args["path"])
        if name is ActionName.PATH_OPEN_FOLDER:
            return await asyncio.to_thread(self.paths.open_folder, args["path"])
        return ExecutionResult(False, "La acción no tiene un ejecutor disponible.")

    async def close(self) -> None:
        await self.browser.close()
