from __future__ import annotations

import ctypes
import os
import subprocess  # nosec B404
import time
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from jarvis.actions.models import ExecutionResult


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


@dataclass(frozen=True, slots=True)
class AppSpec:
    display_name: str
    command: tuple[str, ...]
    window_aliases: tuple[str, ...]


class WindowController:
    def _desktop(self):
        from pywinauto import Desktop

        return Desktop(backend="uia")

    def _visible_windows(self) -> list[Any]:
        windows: list[Any] = []
        for window in self._desktop().windows():
            try:
                title = window.window_text().strip()
                ignored = {"D3DProxyWindow", "Program Manager"}
                if title and window.is_visible() and title not in ignored:
                    windows.append(window)
            except Exception:
                continue
        return windows

    def _foreground(self):
        handle = ctypes.windll.user32.GetForegroundWindow()
        if not handle:
            return None
        try:
            return self._desktop().window(handle=handle)
        except Exception:
            return None

    def find(self, title: str = "", aliases: tuple[str, ...] = ()):
        if not title and not aliases:
            return self._foreground()
        needles = [_normalize(value) for value in (title, *aliases) if value]
        candidates: list[tuple[int, Any]] = []
        for window in self._visible_windows():
            try:
                normalized_title = _normalize(window.window_text())
            except Exception:
                continue
            score = max(
                (
                    3
                    if normalized_title == needle
                    else 2
                    if normalized_title.startswith(needle)
                    else 1
                    for needle in needles
                    if needle in normalized_title
                ),
                default=0,
            )
            if score:
                candidates.append((score, window))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def list_windows(self) -> ExecutionResult:
        titles: list[str] = []
        for window in self._visible_windows():
            title = window.window_text().strip()
            if title not in titles:
                titles.append(title)
            if len(titles) >= 15:
                break
        if not titles:
            return ExecutionResult(True, "No encontré ventanas visibles.", {"windows": []})
        spoken = "; ".join(titles[:8])
        return ExecutionResult(
            True,
            f"Encontré {len(titles)} ventanas. {spoken}",
            {"windows": titles},
        )

    def current(self) -> ExecutionResult:
        window = self._foreground()
        if window is None:
            return ExecutionResult(False, "No pude identificar la ventana activa.")
        try:
            title = window.window_text().strip()
            return ExecutionResult(
                True,
                f"La ventana activa es {title}.",
                {"title": title, "handle": int(window.handle)},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude leer la ventana activa: {exc}")

    def focus(self, title: str = "", aliases: tuple[str, ...] = ()) -> ExecutionResult:
        window = self.find(title, aliases)
        if window is None:
            label = title or (aliases[0] if aliases else "solicitada")
            return ExecutionResult(False, f"No encontré la ventana {label}.")
        try:
            if window.is_minimized():
                window.restore()
            window.set_focus()
            return ExecutionResult(True, f"Ventana enfocada: {window.window_text()}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude enfocar la ventana: {exc}")

    def change_state(self, operation: str, title: str = "") -> ExecutionResult:
        window = self.find(title)
        if window is None:
            return ExecutionResult(False, "No encontré la ventana solicitada.")
        try:
            getattr(window, operation)()
            return ExecutionResult(True, f"Ventana {operation}: {window.window_text()}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude modificar la ventana: {exc}")

    def close(self, title: str = "") -> ExecutionResult:
        window = self.find(title)
        if window is None:
            return ExecutionResult(False, "No encontré la ventana que debía cerrar.")
        name = window.window_text()
        try:
            window.close()
            time.sleep(0.35)
            return ExecutionResult(
                True,
                f"Envié la solicitud de cierre a {name}. Si había cambios pendientes, "
                "la aplicación puede pedir confirmación.",
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude cerrar {name}: {exc}")

    def inspect_controls(self) -> ExecutionResult:
        window = self._foreground()
        if window is None:
            return ExecutionResult(False, "No pude identificar la ventana activa.")
        controls: list[dict[str, str]] = []
        try:
            for control in window.descendants():
                name = control.window_text().strip()
                control_type = str(getattr(control.element_info, "control_type", "Control"))
                if not name or any(item["name"] == name for item in controls):
                    continue
                controls.append({"name": name[:120], "type": control_type})
                if len(controls) >= 40:
                    break
        except Exception as exc:
            return ExecutionResult(False, f"No pude inspeccionar los controles: {exc}")
        preview = "; ".join(item["name"] for item in controls[:10])
        summary = preview or "ninguno con nombre accesible"
        return ExecutionResult(
            True,
            f"Controles visibles en {window.window_text()}: {summary}.",
            {"window": window.window_text(), "controls": controls},
        )

    def click_control(self, target: str) -> ExecutionResult:
        window = self._foreground()
        if window is None:
            return ExecutionResult(False, "No pude identificar la ventana activa.")
        needle = _normalize(target)
        matches: list[tuple[int, Any]] = []
        try:
            for control in window.descendants():
                name = control.window_text().strip()
                normalized_name = _normalize(name)
                if not name or needle not in normalized_name:
                    continue
                score = (
                    3
                    if normalized_name == needle
                    else 2
                    if normalized_name.startswith(needle)
                    else 1
                )
                matches.append((score, control))
        except Exception as exc:
            return ExecutionResult(False, f"No pude recorrer la interfaz: {exc}")
        if not matches:
            return ExecutionResult(False, f"No encontré un control accesible llamado {target}.")
        control = max(matches, key=lambda item: item[0])[1]
        try:
            try:
                control.invoke()
            except Exception:
                control.click_input()
            return ExecutionResult(True, f"Activé el control {control.window_text()}.")
        except Exception as exc:
            return ExecutionResult(False, f"Encontré el control, pero no pude activarlo: {exc}")

    def type_text(self, text: str) -> ExecutionResult:
        from pyperclip import copy, paste
        from pywinauto.keyboard import send_keys

        try:
            previous = paste()
        except Exception:
            previous = ""
        try:
            copy(text)
            send_keys("^v", pause=0.03)
            return ExecutionResult(True, "Escribí el texto en el control que tenía el foco.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude escribir en el control activo: {exc}")
        finally:
            with suppress(Exception):
                copy(previous)

    def send_hotkey(self, hotkey: str) -> ExecutionResult:
        from pywinauto.keyboard import send_keys

        keys = {
            "copy": "^c",
            "paste": "^v",
            "undo": "^z",
            "redo": "^y",
            "save": "^s",
            "select_all": "^a",
        }
        sequence = keys.get(hotkey)
        if sequence is None:
            return ExecutionResult(False, "Ese atajo no está permitido.")
        try:
            send_keys(sequence, pause=0.03)
            return ExecutionResult(True, f"Ejecuté el atajo seguro {hotkey}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude enviar el atajo: {exc}")

    def press_key(self, key: str) -> ExecutionResult:
        from pywinauto.keyboard import send_keys

        keys = {
            "enter": "{ENTER}",
            "escape": "{ESC}",
            "tab": "{TAB}",
            "shift_tab": "+{TAB}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
            "space": "{SPACE}",
            "backspace": "{BACKSPACE}",
        }
        sequence = keys.get(key)
        if sequence is None:
            return ExecutionResult(False, "Esa tecla no está permitida.")
        try:
            send_keys(sequence, pause=0.03)
            return ExecutionResult(True, f"Presioné la tecla segura {key}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude enviar la tecla: {exc}")


class AppController:
    _BLOCKED_TARGETS = frozenset(
        {
            "cmd.exe",
            "cscript.exe",
            "mshta.exe",
            "powershell.exe",
            "pwsh.exe",
            "regedit.exe",
            "wscript.exe",
            "wt.exe",
        }
    )
    APPS = {
        "calculator": AppSpec("calculadora", ("calc.exe",), ("Calculadora", "Calculator")),
        "notepad": AppSpec("bloc de notas", ("notepad.exe",), ("Bloc de notas", "Notepad")),
        "explorer": AppSpec(
            "explorador",
            ("explorer.exe",),
            ("Explorador de archivos", "File Explorer"),
        ),
        "paint": AppSpec("Paint", ("mspaint.exe",), ("Paint",)),
        "settings": AppSpec(
            "Configuración",
            ("explorer.exe", "ms-settings:"),
            ("Configuración", "Settings"),
        ),
        "task_manager": AppSpec(
            "Administrador de tareas",
            ("taskmgr.exe",),
            ("Administrador de tareas", "Task Manager"),
        ),
        "snipping_tool": AppSpec("Recortes", ("snippingtool.exe",), ("Recortes", "Snipping Tool")),
        "character_map": AppSpec(
            "Mapa de caracteres",
            ("charmap.exe",),
            ("Mapa de caracteres", "Character Map"),
        ),
    }

    def __init__(self, windows: WindowController) -> None:
        self.windows = windows
        self._start_menu_roots = tuple(
            path
            for path in (
                Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
                Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            )
            if str(path) and path.exists()
        )

    @property
    def allowed_apps(self) -> frozenset[str]:
        return frozenset(self.APPS)

    @staticmethod
    def _blocked_shortcut(name: str) -> bool:
        normalized = _normalize(name)
        blocked = (
            "powershell",
            "command prompt",
            "simbolo del sistema",
            "terminal",
            "registry editor",
            "editor del registro",
            "windows tools",
        )
        return any(value in normalized for value in blocked)

    def resolve_shortcut(self, requested_name: str) -> Path | None:
        needle = _normalize(requested_name)
        candidates: list[tuple[int, Path]] = []
        for root in self._start_menu_roots:
            for shortcut in root.rglob("*.lnk"):
                if self._blocked_shortcut(shortcut.stem):
                    continue
                normalized_name = _normalize(shortcut.stem)
                if needle not in normalized_name and normalized_name not in needle:
                    continue
                score = (
                    3
                    if normalized_name == needle
                    else 2
                    if normalized_name.startswith(needle)
                    else 1
                )
                candidates.append((score, shortcut))
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def _trusted_shortcut(self, shortcut: Path) -> bool:
        try:
            resolved = shortcut.resolve(strict=True)
        except OSError:
            return False
        if resolved.suffix.casefold() != ".lnk" or not any(
            resolved.is_relative_to(root.resolve()) for root in self._start_menu_roots
        ):
            return False
        try:
            from win32com.client import Dispatch

            target = Dispatch("WScript.Shell").CreateShortcut(str(resolved)).TargetPath
        except Exception:
            return False
        return not target or Path(target).name.casefold() not in self._BLOCKED_TARGETS

    def _wait_for_window(self, aliases: tuple[str, ...], timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            window = self.windows.find(aliases=aliases)
            if window is not None:
                return window
            time.sleep(0.2)
        return None

    def open(self, app_name: str, shortcut_path: str = "") -> ExecutionResult:
        spec = self.APPS.get(app_name)
        if spec is None:
            shortcut = Path(shortcut_path) if shortcut_path else self.resolve_shortcut(app_name)
            if shortcut is None or not self._trusted_shortcut(shortcut):
                return ExecutionResult(False, "La aplicación no está permitida o ya no existe.")
            try:
                os.startfile(shortcut)  # type: ignore[attr-defined]  # nosec B606
            except OSError as exc:
                return ExecutionResult(False, f"Windows no pudo abrir {shortcut.stem}: {exc}")
            time.sleep(0.55)
            focused = self.windows.focus(title=shortcut.stem)
            return ExecutionResult(
                True,
                f"Abrí la aplicación instalada {shortcut.stem}.",
                {"verified": focused.success, "shortcut": str(shortcut)},
            )
        existing = self.windows.find(aliases=spec.window_aliases)
        if existing is not None:
            focused = self.windows.focus(aliases=spec.window_aliases)
            if focused.success:
                return ExecutionResult(
                    True,
                    f"{spec.display_name} ya estaba abierta; la traje al frente.",
                    {"verified": True, "already_open": True},
                )
        try:
            process = subprocess.Popen(  # nosec B603
                list(spec.command),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            return ExecutionResult(False, f"Windows no pudo abrir {spec.display_name}: {exc}")
        time.sleep(0.2)
        if process.poll() not in {None, 0}:
            return ExecutionResult(False, f"{spec.display_name} terminó con un error al iniciar.")
        window = self._wait_for_window(spec.window_aliases)
        verified = window is not None
        if verified:
            self.windows.focus(aliases=spec.window_aliases)
        verification = " y verifiqué su ventana" if verified else ""
        return ExecutionResult(
            True,
            f"Abrí {spec.display_name}{verification}.",
            {"verified": verified, "pid": process.pid},
        )


class AudioController:
    _RPC_E_CHANGED_MODE = -2147417850
    _MEDIA_KEYS = {
        "mute": 0xAD,
        "down": 0xAE,
        "up": 0xAF,
        "next": 0xB0,
        "previous": 0xB1,
        "stop": 0xB2,
        "play_pause": 0xB3,
    }
    _KEYEVENTF_KEYUP = 0x0002

    @staticmethod
    def _endpoint():
        import comtypes
        from pycaw.pycaw import AudioUtilities

        initialized_here = False
        try:
            comtypes.CoInitialize()
            initialized_here = True
        except OSError as exc:
            error_code = getattr(exc, "winerror", None)
            if error_code is None and exc.args and isinstance(exc.args[0], int):
                error_code = exc.args[0]
            if error_code != AudioController._RPC_E_CHANGED_MODE:
                raise
            # PyWinAuto may already have initialized this worker in the other valid COM
            # apartment. Reusing that apartment is safe; it must not be uninitialized here.
        cleanup = comtypes if initialized_here else None
        return AudioUtilities.GetSpeakers().EndpointVolume, cleanup

    def set_level(self, level: int) -> ExecutionResult:
        endpoint = None
        comtypes_module = None
        try:
            endpoint, comtypes_module = self._endpoint()
            endpoint.SetMasterVolumeLevelScalar(level / 100, None)
            actual = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            return ExecutionResult(
                abs(actual - level) <= 1,
                f"Volumen establecido en {actual} por ciento.",
                {"level": actual, "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude establecer el volumen: {exc}")
        finally:
            if comtypes_module is not None:
                comtypes_module.CoUninitialize()

    def get_level(self) -> ExecutionResult:
        comtypes_module = None
        try:
            endpoint, comtypes_module = self._endpoint()
            level = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            muted = bool(endpoint.GetMute())
            suffix = " y está silenciado" if muted else ""
            return ExecutionResult(
                True,
                f"El volumen está en {level} por ciento{suffix}.",
                {"level": level, "muted": muted, "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude consultar el volumen: {exc}")
        finally:
            if comtypes_module is not None:
                comtypes_module.CoUninitialize()

    def change_level(self, step: int) -> ExecutionResult:
        endpoint = None
        comtypes_module = None
        try:
            endpoint, comtypes_module = self._endpoint()
            current = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            target = max(0, min(100, current + step))
            endpoint.SetMasterVolumeLevelScalar(target / 100, None)
            actual = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            return ExecutionResult(
                True,
                f"Cambié el volumen de {current} a {actual} por ciento.",
                {"previous": current, "level": actual, "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude cambiar el volumen: {exc}")
        finally:
            if comtypes_module is not None:
                comtypes_module.CoUninitialize()

    def mute(self, muted: bool) -> ExecutionResult:
        endpoint = None
        comtypes_module = None
        try:
            endpoint, comtypes_module = self._endpoint()
            endpoint.SetMute(1 if muted else 0, None)
            actual = bool(endpoint.GetMute())
            state = "silenciado" if actual else "con sonido"
            return ExecutionResult(
                actual is muted,
                f"El audio quedó {state}.",
                {"muted": actual, "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude cambiar el silencio: {exc}")
        finally:
            if comtypes_module is not None:
                comtypes_module.CoUninitialize()

    def media_key(self, name: str) -> ExecutionResult:
        virtual_key = self._MEDIA_KEYS.get(name)
        if virtual_key is None:
            return ExecutionResult(False, "Tecla multimedia no permitida.")
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.keybd_event(virtual_key, 0, 0, 0)
            user32.keybd_event(virtual_key, 0, self._KEYEVENTF_KEYUP, 0)
            return ExecutionResult(True, f"Envié el control multimedia {name}.")
        except (OSError, AttributeError) as exc:
            return ExecutionResult(False, f"No pude controlar la reproducción: {exc}")


class DesktopInputController:
    @staticmethod
    def _cursor_position() -> tuple[int, int]:
        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        point = Point()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            raise OSError("Windows no devolvió la posición del cursor")
        return int(point.x), int(point.y)

    def move(self, x: int, y: int) -> ExecutionResult:
        user32 = ctypes.windll.user32
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        right = left + user32.GetSystemMetrics(78)
        bottom = top + user32.GetSystemMetrics(79)
        if not (left <= x < right and top <= y < bottom):
            return ExecutionResult(False, "Las coordenadas están fuera de las pantallas activas.")
        try:
            from pywinauto.mouse import move

            move(coords=(x, y))
            return ExecutionResult(True, f"Moví el cursor a las coordenadas {x}, {y}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude mover el cursor: {exc}")

    def click(self, x: int, y: int) -> ExecutionResult:
        user32 = ctypes.windll.user32
        left = user32.GetSystemMetrics(76)
        top = user32.GetSystemMetrics(77)
        right = left + user32.GetSystemMetrics(78)
        bottom = top + user32.GetSystemMetrics(79)
        if not (left <= x < right and top <= y < bottom):
            return ExecutionResult(False, "Las coordenadas están fuera de las pantallas activas.")
        try:
            from pywinauto.mouse import click

            click(coords=(x, y))
            return ExecutionResult(True, f"Hice clic en las coordenadas {x}, {y}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude hacer clic: {exc}")

    def click_if_cursor_unchanged(
        self,
        x: int,
        y: int,
        tolerance: int = 8,
    ) -> ExecutionResult:
        try:
            current_x, current_y = self._cursor_position()
        except Exception as exc:
            return ExecutionResult(False, f"No pude verificar el cursor: {exc}")
        if abs(current_x - x) > tolerance or abs(current_y - y) > tolerance:
            return ExecutionResult(
                False,
                "El cursor se movió desde la posición revisada; cancelé el clic visual.",
                {"cursor_moved_by_user": True},
            )
        return self.click(x, y)

    def scroll(self, amount: int) -> ExecutionResult:
        try:
            from pywinauto.mouse import scroll

            scroll(wheel_dist=amount)
            direction = "arriba" if amount > 0 else "abajo"
            return ExecutionResult(True, f"Desplacé la vista hacia {direction}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude desplazar la vista: {exc}")

    def screenshot(self, output_dir: Path) -> ExecutionResult:
        try:
            from PIL import ImageGrab

            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / (f"desktop-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.png")
            ImageGrab.grab(all_screens=True).save(path, format="PNG")
            return ExecutionResult(
                True,
                "Tomé una captura y la guardé localmente.",
                {"path": str(path), "verified": path.exists()},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude capturar la pantalla: {exc}")

    def show_desktop(self) -> ExecutionResult:
        try:
            from pywinauto.keyboard import send_keys

            send_keys("#d", pause=0.03)
            return ExecutionResult(True, "Mostré el escritorio.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude mostrar el escritorio: {exc}")


class ClipboardController:
    def read(self) -> ExecutionResult:
        try:
            from pyperclip import paste

            content = paste()
            if not content:
                return ExecutionResult(True, "El portapapeles de texto está vacío.", {"text": ""})
            excerpt = content[:2_000]
            return ExecutionResult(
                True,
                f"El portapapeles contiene: {excerpt}",
                {"text": excerpt, "truncated": len(content) > len(excerpt)},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude leer el portapapeles: {exc}")

    def write(self, text: str) -> ExecutionResult:
        try:
            from pyperclip import copy

            copy(text)
            return ExecutionResult(True, "Copié el texto indicado al portapapeles.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude escribir en el portapapeles: {exc}")


class SystemInfoController:
    def status(self) -> ExecutionResult:
        try:
            import psutil

            memory = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            details: dict[str, Any] = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": round(memory.percent, 1),
                "memory_available_gb": round(memory.available / (1024**3), 1),
            }
            battery_text = ""
            if battery is not None:
                details["battery_percent"] = round(battery.percent)
                details["plugged_in"] = battery.power_plugged
                battery_text = f", batería {round(battery.percent)} por ciento"
            return ExecutionResult(
                True,
                f"CPU {details['cpu_percent']} por ciento, memoria "
                f"{details['memory_percent']} por ciento{battery_text}.",
                details,
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude consultar el estado del sistema: {exc}")


class PathController:
    _ALLOWED_FILE_EXTENSIONS = {
        ".avi",
        ".bmp",
        ".csv",
        ".docx",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".json",
        ".log",
        ".md",
        ".mkv",
        ".mp3",
        ".mp4",
        ".odp",
        ".ods",
        ".odt",
        ".pdf",
        ".png",
        ".pptx",
        ".txt",
        ".wav",
        ".webp",
        ".xlsx",
        ".yaml",
        ".yml",
        ".zip",
    }

    @staticmethod
    def _resolve(raw_path: str) -> Path:
        aliases = {
            "descargas": Path.home() / "Downloads",
            "downloads": Path.home() / "Downloads",
            "documentos": Path.home() / "Documents",
            "documents": Path.home() / "Documents",
            "escritorio": Path.home() / "Desktop",
            "desktop": Path.home() / "Desktop",
            "imagenes": Path.home() / "Pictures",
            "pictures": Path.home() / "Pictures",
            "musica": Path.home() / "Music",
            "music": Path.home() / "Music",
            "videos": Path.home() / "Videos",
        }
        candidate = aliases.get(_normalize(raw_path.strip()), Path(raw_path).expanduser())
        return candidate.resolve()

    def open_folder(self, raw_path: str) -> ExecutionResult:
        path = self._resolve(raw_path)
        if not path.is_dir():
            return ExecutionResult(False, "La carpeta no existe o no es accesible.")
        try:
            subprocess.Popen(["explorer.exe", str(path)], close_fds=True)  # nosec B603
            return ExecutionResult(True, f"Abrí la carpeta {path.name}.", {"path": str(path)})
        except OSError as exc:
            return ExecutionResult(False, f"No pude abrir la carpeta: {exc}")

    def open_file(self, raw_path: str) -> ExecutionResult:
        path = self._resolve(raw_path)
        if not path.is_file():
            return ExecutionResult(False, "El archivo no existe o no es accesible.")
        if path.suffix.casefold() not in self._ALLOWED_FILE_EXTENSIONS:
            return ExecutionResult(
                False,
                "Ese tipo de archivo no pertenece a la lista segura permitida.",
            )
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # nosec B606
            return ExecutionResult(True, f"Abrí el archivo {path.name}.", {"path": str(path)})
        except OSError as exc:
            return ExecutionResult(False, f"No pude abrir el archivo: {exc}")
