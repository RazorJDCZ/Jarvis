from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess  # nosec B404
import time
import winreg
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx

from jarvis.actions.models import ExecutionResult


@dataclass(frozen=True, slots=True)
class BrowserSpec:
    key: str
    display_name: str
    candidates: tuple[Path, ...]


class ControlledBrowser:
    _ALIASES = {
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

    _WINDOW_ALIASES = {
        "chrome": ("Google Chrome",),
        "edge": ("Microsoft Edge",),
        "brave": ("Brave",),
    }

    def __init__(
        self,
        data_dir: Path,
        search_url: str,
        personal_profile: bool = False,
        windows: Any | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.search_url = search_url
        self.personal_profile = personal_profile
        self.windows = windows
        self._process: subprocess.Popen[bytes] | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._port: int | None = None
        self._active_browser: str | None = None
        self._personal_active = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _specs() -> dict[str, BrowserSpec]:
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        return {
            "chrome": BrowserSpec(
                "chrome",
                "Google Chrome",
                (
                    program_files / "Google/Chrome/Application/chrome.exe",
                    program_files_x86 / "Google/Chrome/Application/chrome.exe",
                    local_app_data / "Google/Chrome/Application/chrome.exe",
                ),
            ),
            "edge": BrowserSpec(
                "edge",
                "Microsoft Edge",
                (
                    program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
                    program_files / "Microsoft/Edge/Application/msedge.exe",
                    local_app_data / "Microsoft/Edge/Application/msedge.exe",
                ),
            ),
            "brave": BrowserSpec(
                "brave",
                "Brave",
                (
                    program_files / "BraveSoftware/Brave-Browser/Application/brave.exe",
                    program_files_x86 / "BraveSoftware/Brave-Browser/Application/brave.exe",
                    local_app_data / "BraveSoftware/Brave-Browser/Application/brave.exe",
                ),
            ),
        }

    @classmethod
    def _browser_path(cls, browser: str) -> Path | None:
        spec = cls._specs().get(browser)
        if spec is None:
            return None
        for candidate in spec.candidates:
            if candidate.exists():
                return candidate
        executable = {"chrome": "chrome", "edge": "msedge", "brave": "brave"}[browser]
        discovered = shutil.which(executable)
        return Path(discovered) if discovered else None

    @classmethod
    def installed_browsers(cls) -> tuple[str, ...]:
        return tuple(key for key in cls._specs() if cls._browser_path(key) is not None)

    @staticmethod
    def _windows_default_browser() -> str | None:
        key_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                prog_id = str(winreg.QueryValueEx(key, "ProgId")[0]).casefold()
        except OSError:
            return None
        if "chrome" in prog_id:
            return "chrome"
        if "brave" in prog_id:
            return "brave"
        if "edge" in prog_id:
            return "edge"
        return None

    @classmethod
    def normalize_browser(cls, requested: str | None) -> str:
        normalized = (requested or "default").strip().casefold()
        browser = cls._ALIASES.get(normalized)
        if browser is None:
            raise ValueError("ese navegador no es compatible con el control seguro")
        installed = cls.installed_browsers()
        if browser == "default":
            preferred = cls._windows_default_browser()
            if preferred in installed:
                return preferred
            if installed:
                return installed[0]
            raise RuntimeError("no encontré Chrome, Edge ni Brave instalados")
        if browser not in installed:
            display = cls._specs()[browser].display_name
            raise RuntimeError(f"{display} no está instalado")
        return browser

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    @staticmethod
    def _launch_arguments(
        executable: Path,
        port: int,
        profile: Path,
    ) -> list[str]:
        return [
            str(executable),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "about:blank",
        ]

    @staticmethod
    def _personal_user_data_dir(browser: str) -> Path:
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        relative = {
            "chrome": "Google/Chrome/User Data",
            "edge": "Microsoft/Edge/User Data",
            "brave": "BraveSoftware/Brave-Browser/User Data",
        }[browser]
        return local_app_data / relative

    @classmethod
    def _personal_profile_directory(cls, browser: str) -> str | None:
        local_state = cls._personal_user_data_dir(browser) / "Local State"
        try:
            if not local_state.is_file() or local_state.stat().st_size > 4_000_000:
                return None
            data = json.loads(local_state.read_text(encoding="utf-8"))
            profile = data.get("profile", {})
            candidate = profile.get("last_used")
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            return None
        if not isinstance(candidate, str):
            return None
        if candidate == "Default" or re.fullmatch(r"Profile \d+", candidate):
            return candidate
        return None

    @classmethod
    def _personal_launch_arguments(
        cls,
        executable: Path,
        browser: str,
        url: str | None = None,
    ) -> list[str]:
        arguments = [str(executable)]
        profile = cls._personal_profile_directory(browser)
        if profile:
            arguments.append(f"--profile-directory={profile}")
        arguments.append("--new-window")
        if url:
            arguments.append(url)
        return arguments

    @staticmethod
    def _validate_http_url(url: str) -> None:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("la dirección contiene un puerto inválido") from exc
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("la dirección contiene un puerto inválido")
        if (
            len(url) > 2_048
            or any(character in url for character in "\r\n\t")
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("solo se permiten direcciones HTTP o HTTPS sin credenciales")

    async def status(self) -> ExecutionResult:
        installed = self.installed_browsers()
        available = bool(installed)
        names = [self._specs()[name].display_name for name in installed]
        default = None
        if available:
            with suppress(RuntimeError, ValueError):
                default = self.normalize_browser(None)
        message = (
            f"Navegadores controlables disponibles: {', '.join(names)}."
            if available
            else "No encontré Chrome, Edge ni Brave instalados."
        )
        return ExecutionResult(
            available,
            message,
            {
                "running": self._page is not None or self._personal_active,
                "active_browser": self._active_browser,
                "default_browser": default,
                "installed_browsers": list(installed),
                "profile_mode": "personal" if self.personal_profile else "jarvis-persistent",
            },
        )

    def _focus_personal_browser(self, browser: str) -> ExecutionResult:
        if self.windows is None:
            return ExecutionResult(False, "No esta disponible el control de ventanas de Windows.")
        return self.windows.focus(aliases=self._WINDOW_ALIASES[browser])

    def _launch_personal(self, url: str | None, requested_browser: str | None) -> ExecutionResult:
        browser = self.normalize_browser(requested_browser or self._active_browser)
        executable = self._browser_path(browser)
        if executable is None:
            display = self._specs()[browser].display_name
            return ExecutionResult(False, f"{display} no esta instalado.")
        arguments = self._personal_launch_arguments(executable, browser, url)
        try:
            process = subprocess.Popen(  # nosec B603
                arguments,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            return ExecutionResult(False, f"Windows no pudo abrir el navegador: {exc}")
        time.sleep(0.55)
        if process.poll() not in {None, 0}:
            return ExecutionResult(False, "El navegador termino con un error al iniciar.")
        focused = self._focus_personal_browser(browser)
        self._active_browser = browser
        self._personal_active = True
        display = self._specs()[browser].display_name
        return ExecutionResult(
            True,
            f"Abri la pagina en {display} con tu perfil personal.",
            {
                "url": url or "",
                "browser": browser,
                "profile_mode": "personal",
                "verified": focused.success,
                "window_focused": focused.success,
            },
        )

    def _personal_shortcut(self, shortcut: str, success_message: str) -> ExecutionResult:
        browser = self._active_browser
        if not self._personal_active or browser is None:
            return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
        focused = self._focus_personal_browser(browser)
        if not focused.success:
            return focused
        if self.windows is None:
            return ExecutionResult(False, "No esta disponible el control de ventanas de Windows.")
        result = self.windows.send_browser_shortcut(shortcut)
        if not result.success:
            return result
        return ExecutionResult(True, success_message, {"profile_mode": "personal"})

    def _terminate_process(self, graceful_timeout: float = 0.0) -> None:
        if self._process is None or self._process.poll() is not None:
            self._process = None
            return
        if graceful_timeout > 0:
            try:
                self._process.wait(timeout=graceful_timeout)
                self._process = None
                return
            except subprocess.TimeoutExpired:
                pass
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            with suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=2)
        self._process = None

    async def _close_session(self) -> None:
        try:
            if self._browser is not None:
                try:
                    cdp_session = await self._browser.new_browser_cdp_session()
                    await cdp_session.send("Browser.close")
                except Exception:
                    with suppress(Exception):
                        await self._browser.close()
        finally:
            self._browser = None
            self._context = None
            self._page = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            await asyncio.to_thread(self._terminate_process, 3.0)
            self._port = None
            self._active_browser = None

    async def _ensure_page(self, requested_browser: str | None = None):
        async with self._lock:
            browser_name = self.normalize_browser(requested_browser or self._active_browser)
            if (
                self._page is not None
                and not self._page.is_closed()
                and self._active_browser == browser_name
            ):
                return self._page
            if self._page is not None or self._process is not None:
                await self._close_session()
            executable = self._browser_path(browser_name)
            if executable is None:
                raise RuntimeError(f"{self._specs()[browser_name].display_name} no está instalado")
            self._port = self._free_port()
            profile = self.data_dir / f"browser-profile-{browser_name}"
            profile.mkdir(parents=True, exist_ok=True)
            spec = self._specs()[browser_name]
            arguments = self._launch_arguments(executable, self._port, profile)
            self._process = subprocess.Popen(  # nosec B603
                arguments,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            endpoint = f"http://127.0.0.1:{self._port}"
            ready = False
            async with httpx.AsyncClient(timeout=1.0) as client:
                for _ in range(40):
                    try:
                        response = await client.get(f"{endpoint}/json/version")
                        response.raise_for_status()
                        ready = True
                        break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.2)
            if not ready:
                await asyncio.to_thread(self._terminate_process)
                self._port = None
                raise RuntimeError(f"{spec.display_name} no habilitó el canal de automatización")
            from playwright.async_api import async_playwright

            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
                self._context = self._browser.contexts[0]
                pages = [page for page in self._context.pages if not page.is_closed()]
                self._page = pages[0] if pages else await self._context.new_page()
                for stale_page in pages[1:]:
                    await stale_page.close()
                if self._page.url != "about:blank":
                    await self._page.goto("about:blank")
                self._active_browser = browser_name
                return self._page
            except Exception:
                if self._playwright is not None:
                    with suppress(Exception):
                        await self._playwright.stop()
                self._playwright = None
                self._browser = None
                self._context = None
                self._page = None
                await asyncio.to_thread(self._terminate_process)
                self._port = None
                self._active_browser = None
                raise

    async def open(self, url: str, browser: str | None = None) -> ExecutionResult:
        try:
            self._validate_http_url(url)
            if self.personal_profile:
                return await asyncio.to_thread(self._launch_personal, url, browser)
            page = await self._ensure_page(browser)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._validate_http_url(page.url)
            await page.bring_to_front()
            browser_name = self._active_browser or self.normalize_browser(browser)
            display = self._specs()[browser_name].display_name
            return ExecutionResult(
                True,
                f"Abrí {await page.title() or url} en {display}.",
                {
                    "url": page.url,
                    "title": await page.title(),
                    "browser": browser_name,
                    "verified": True,
                },
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude abrir la página: {exc}")

    async def search(self, query: str, browser: str | None = None) -> ExecutionResult:
        try:
            template_without_query = self.search_url.replace("{query}", "", 1)
            if (
                self.search_url.count("{query}") != 1
                or "{" in template_without_query
                or "}" in template_without_query
            ):
                raise ValueError("la plantilla de búsqueda debe contener exactamente {query}")
            url = self.search_url.format(query=quote_plus(query))
            self._validate_http_url(url)
        except (IndexError, KeyError, ValueError) as exc:
            return ExecutionResult(False, f"No pude preparar la búsqueda: {exc}")
        return await self.open(url, browser)

    async def navigate(self, direction: str) -> ExecutionResult:
        if self.personal_profile:
            messages = {
                "back": "Volvi a la pagina anterior.",
                "forward": "Avance a la pagina siguiente.",
                "refresh": "Actualice la pagina.",
            }
            shortcut = direction if direction in {"back", "forward"} else "refresh"
            return await asyncio.to_thread(
                self._personal_shortcut,
                shortcut,
                messages[shortcut],
            )
        try:
            page = await self._ensure_page()
            if direction == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=15_000)
            elif direction == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=15_000)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=15_000)
            title = await page.title()
            return ExecutionResult(True, f"Navegación completada. Página actual: {title}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude navegar: {exc}")

    async def new_tab(self, browser: str | None = None) -> ExecutionResult:
        if self.personal_profile:
            if not self._personal_active:
                return await asyncio.to_thread(self._launch_personal, None, browser)
            return await asyncio.to_thread(
                self._personal_shortcut,
                "new_tab",
                "Abri una pestana nueva en tu perfil personal.",
            )
        try:
            await self._ensure_page(browser)
            self._page = await self._context.new_page()
            await self._page.bring_to_front()
            return ExecutionResult(True, "Abrí una pestaña nueva controlada por Jarvis.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude crear la pestaña: {exc}")

    async def list_tabs(self) -> ExecutionResult:
        if self.personal_profile:
            browser = self._active_browser
            if not self._personal_active or browser is None:
                return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
            focused = await asyncio.to_thread(self._focus_personal_browser, browser)
            if not focused.success or self.windows is None:
                return focused
            inspected = await asyncio.to_thread(self.windows.inspect_controls)
            controls = inspected.details.get("controls", []) if inspected.success else []
            tabs = [
                item
                for item in controls
                if str(item.get("type", "")).casefold() in {"tab", "tabitem"}
            ]
            if not tabs:
                return ExecutionResult(
                    False,
                    "Chrome no expuso los nombres de sus pestanas a la accesibilidad de Windows.",
                )
            names = [str(item.get("name", "")) for item in tabs[:12]]
            return ExecutionResult(
                True,
                f"Pestanas visibles: {'; '.join(names)}.",
                {"tabs": names, "profile_mode": "personal"},
            )
        try:
            await self._ensure_page()
            tabs = [
                {"title": await page.title(), "url": page.url}
                for page in self._context.pages
                if not page.is_closed()
            ]
            preview = "; ".join(tab["title"] or tab["url"] for tab in tabs[:8])
            return ExecutionResult(
                True,
                f"Hay {len(tabs)} pestañas: {preview}.",
                {"tabs": tabs},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude listar las pestañas: {exc}")

    async def switch_tab(self, target: str) -> ExecutionResult:
        if self.personal_profile:
            browser = self._active_browser
            if not self._personal_active or browser is None or self.windows is None:
                return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
            focused = await asyncio.to_thread(self._focus_personal_browser, browser)
            if not focused.success:
                return focused
            result = await asyncio.to_thread(self.windows.click_control, target)
            return ExecutionResult(
                result.success,
                (
                    f"Cambie a la pestana relacionada con {target}."
                    if result.success
                    else result.message
                ),
                {"profile_mode": "personal", **result.details},
            )
        try:
            await self._ensure_page()
            needle = target.casefold()
            for page in self._context.pages:
                title = await page.title()
                if needle in title.casefold() or needle in page.url.casefold():
                    self._page = page
                    await page.bring_to_front()
                    return ExecutionResult(True, f"Cambié a la pestaña {title or page.url}.")
            return ExecutionResult(False, f"No encontré una pestaña relacionada con {target}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude cambiar de pestaña: {exc}")

    async def close_tab(self) -> ExecutionResult:
        if self.personal_profile:
            return await asyncio.to_thread(
                self._personal_shortcut,
                "close_tab",
                "Cerre la pestana activa de tu navegador personal.",
            )
        try:
            page = await self._ensure_page()
            title = await page.title()
            await page.close()
            remaining = [
                candidate for candidate in self._context.pages if not candidate.is_closed()
            ]
            self._page = remaining[-1] if remaining else await self._context.new_page()
            await self._page.bring_to_front()
            return ExecutionResult(True, f"Cerré la pestaña {title or 'actual'}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude cerrar la pestaña: {exc}")

    async def read(self) -> ExecutionResult:
        if self.personal_profile:
            browser = self._active_browser
            if not self._personal_active or browser is None or self.windows is None:
                return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
            focused = await asyncio.to_thread(self._focus_personal_browser, browser)
            if not focused.success:
                return focused
            inspected = await asyncio.to_thread(self.windows.inspect_controls)
            if not inspected.success:
                return inspected
            return ExecutionResult(
                True,
                inspected.message,
                {**inspected.details, "profile_mode": "personal", "method": "accessibility"},
            )
        try:
            page = await self._ensure_page()
            body = await page.locator("body").inner_text(timeout=10_000)
            clean = " ".join(body.split())
            excerpt = clean[:1_500]
            return ExecutionResult(
                True,
                f"Página {await page.title()}. {excerpt[:700]}",
                {"url": page.url, "title": await page.title(), "text": excerpt},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude leer la página: {exc}")

    async def click(self, target: str) -> ExecutionResult:
        if self.personal_profile:
            browser = self._active_browser
            if not self._personal_active or browser is None or self.windows is None:
                return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
            focused = await asyncio.to_thread(self._focus_personal_browser, browser)
            if not focused.success:
                return focused
            result = await asyncio.to_thread(self.windows.click_control, target)
            return ExecutionResult(
                result.success,
                (
                    f"Hice clic en {target} usando la accesibilidad de Windows."
                    if result.success
                    else result.message
                ),
                {**result.details, "profile_mode": "personal", "verified": result.success},
            )
        try:
            page = await self._ensure_page()
            candidates = (
                page.get_by_role("button", name=target, exact=False),
                page.get_by_role("link", name=target, exact=False),
                page.get_by_text(target, exact=False),
            )
            for locator in candidates:
                if await locator.count():
                    await locator.first.click(timeout=10_000)
                    await page.wait_for_timeout(350)
                    return ExecutionResult(
                        True,
                        f"Hice clic en {target}. Página actual: {await page.title()}.",
                        {"url": page.url, "verified": True},
                    )
            return ExecutionResult(False, f"No encontré un botón o enlace llamado {target}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude hacer clic en la página: {exc}")

    async def fill(self, field: str, text: str) -> ExecutionResult:
        if self.personal_profile:
            browser = self._active_browser
            if not self._personal_active or browser is None or self.windows is None:
                return ExecutionResult(False, "Primero abre una pagina con Jarvis.")
            focused = await asyncio.to_thread(self._focus_personal_browser, browser)
            if not focused.success:
                return focused
            clicked = await asyncio.to_thread(self.windows.click_control, field)
            if not clicked.success:
                return clicked
            typed = await asyncio.to_thread(self.windows.type_text, text)
            return ExecutionResult(
                typed.success,
                (
                    f"Escribi el texto en {field}, sin enviarlo."
                    if typed.success
                    else typed.message
                ),
                {"field": field, "profile_mode": "personal", "verified": typed.success},
            )
        try:
            page = await self._ensure_page()
            candidates = (
                page.get_by_label(field, exact=False),
                page.get_by_placeholder(field, exact=False),
                page.get_by_role("textbox", name=field, exact=False),
            )
            for locator in candidates:
                if await locator.count():
                    await locator.first.fill(text, timeout=10_000)
                    return ExecutionResult(
                        True,
                        f"Escribí el texto en el campo {field}, sin enviarlo.",
                        {"field": field, "verified": True},
                    )
            return ExecutionResult(False, f"No encontré el campo {field}.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude completar el campo: {exc}")

    async def open_result(self, index: int) -> ExecutionResult:
        if self.personal_profile:
            return ExecutionResult(
                False,
                (
                    "En el perfil personal no puedo identificar con seguridad un resultado solo "
                    "por su numero. Pideme hacer clic por el nombre visible del enlace."
                ),
            )
        try:
            page = await self._ensure_page()
            result_links = page.locator("a:has(h3)")
            if await result_links.count() < index:
                return ExecutionResult(
                    False,
                    f"No encontré el resultado número {index} en la página actual.",
                )
            link = result_links.nth(index - 1)
            title = " ".join((await link.inner_text(timeout=5_000)).split())[:300]
            href = await link.get_attribute("href")
            if not href:
                return ExecutionResult(False, "El resultado no contiene un enlace navegable.")
            destination = urljoin(page.url, href)
            self._validate_http_url(destination)
            await page.goto(destination, wait_until="domcontentloaded", timeout=30_000)
            self._validate_http_url(page.url)
            await page.bring_to_front()
            return ExecutionResult(
                True,
                f"Abrí el resultado {index}: {title or await page.title()}.",
                {"index": index, "title": title, "url": page.url, "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude abrir ese resultado: {exc}")

    async def close(self) -> None:
        async with self._lock:
            if self._personal_active:
                # Las ventanas pertenecen al usuario. Al apagar Jarvis nunca debe cerrarlas.
                self._personal_active = False
                self._active_browser = None
                return
            await self._close_session()
