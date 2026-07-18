from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess  # nosec B404
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit

import httpx

from jarvis.actions.models import ExecutionResult


class ControlledBrowser:
    def __init__(self, data_dir: Path, search_url: str) -> None:
        self.data_dir = data_dir
        self.search_url = search_url
        self._process: subprocess.Popen[bytes] | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._port: int | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _edge_path() -> Path | None:
        candidates = (
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        discovered = shutil.which("msedge")
        return Path(discovered) if discovered else None

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

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
        available = self._edge_path() is not None
        message = (
            "Edge controlado está disponible." if available else "Microsoft Edge no está instalado."
        )
        return ExecutionResult(
            available,
            message,
            {"running": self._page is not None},
        )

    def _terminate_process(self) -> None:
        if self._process is None or self._process.poll() is not None:
            self._process = None
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            with suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=2)
        self._process = None

    async def _ensure_page(self):
        async with self._lock:
            if self._page is not None and not self._page.is_closed():
                return self._page
            edge = self._edge_path()
            if edge is None:
                raise RuntimeError("Microsoft Edge no está instalado")
            self._port = self._free_port()
            profile = self.data_dir / "browser-profile"
            profile.mkdir(parents=True, exist_ok=True)
            arguments = [
                str(edge),
                f"--remote-debugging-port={self._port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--inprivate",
                "about:blank",
            ]
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
                raise RuntimeError("Edge no habilitó el canal de automatización")
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
                raise

    async def open(self, url: str) -> ExecutionResult:
        try:
            self._validate_http_url(url)
            page = await self._ensure_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            self._validate_http_url(page.url)
            await page.bring_to_front()
            return ExecutionResult(
                True,
                f"Abrí {await page.title() or url}.",
                {"url": page.url, "title": await page.title(), "verified": True},
            )
        except Exception as exc:
            return ExecutionResult(False, f"No pude abrir la página: {exc}")

    async def search(self, query: str) -> ExecutionResult:
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
        return await self.open(url)

    async def navigate(self, direction: str) -> ExecutionResult:
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

    async def new_tab(self) -> ExecutionResult:
        try:
            await self._ensure_page()
            self._page = await self._context.new_page()
            await self._page.bring_to_front()
            return ExecutionResult(True, "Abrí una pestaña nueva controlada por Jarvis.")
        except Exception as exc:
            return ExecutionResult(False, f"No pude crear la pestaña: {exc}")

    async def list_tabs(self) -> ExecutionResult:
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
            try:
                if self._browser is not None:
                    await self._browser.close()
            finally:
                self._browser = None
                self._context = None
                self._page = None
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None
                await asyncio.to_thread(self._terminate_process)
                self._port = None
