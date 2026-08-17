from __future__ import annotations

import asyncio
import json
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

from jarvis.config import Settings
from jarvis.main import create_app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def temporary_project() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="jarvis-offline-smoke-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def start_server(project_root: Path, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    settings = Settings(
        project_root=project_root,
        host="127.0.0.1",
        port=port,
        brain_mode="fallback",
        action_model_planning=False,
        memory_enabled=False,
        remote_access_enabled=False,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server, thread
        time.sleep(0.05)
    raise RuntimeError("El servidor de prueba no inició.")


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=5)


async def verify() -> dict[str, object]:
    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    with temporary_project() as project_root:
        server, server_thread = start_server(project_root, port)
        recovered_server: uvicorn.Server | None = None
        recovered_thread: threading.Thread | None = None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome", headless=True)
                context = await browser.new_context(service_workers="allow")
                page = await context.new_page()
                await page.goto(origin)
                await page.locator("#textInput").wait_for(state="visible")
                await page.evaluate("navigator.serviceWorker.ready")
                await page.reload(wait_until="domcontentloaded")
                await page.locator("#remoteGate").wait_for(state="hidden")

                await page.close()
                stop_server(server, server_thread)
                page = await context.new_page()
                await page.goto(origin, wait_until="domcontentloaded")
                await page.locator("#remoteOfflinePanel").wait_for(state="visible")
                title = await page.locator("#remoteGateTitle").inner_text()
                identity = await page.locator("#remoteIdentityLabel").inner_text()
                detail = await page.locator("#remoteOfflineDescription").inner_text()
                pairing_hidden = await page.locator("#remotePairingForm").is_hidden()
                raw_error = await page.locator("#remoteGateError").inner_text()

                recovered_server, recovered_thread = start_server(project_root, port)
                await page.locator("#retryCoreButton").click()
                await page.locator("#remoteGate").wait_for(state="hidden", timeout=10_000)
                recovered = await page.locator("#textInput").is_visible()
                await browser.close()
                return {
                    "offline_title_is_clear": title == "Jarvis no está en ejecución",
                    "offline_explains_cached_ui": "caché" in identity and "start.cmd" in detail,
                    "pairing_controls_hidden_offline": pairing_hidden,
                    "raw_fetch_error_hidden": "Failed to fetch" not in raw_error,
                    "recovers_without_pairing": recovered,
                }
        finally:
            if server_thread.is_alive():
                stop_server(server, server_thread)
            if recovered_server is not None and recovered_thread is not None:
                stop_server(recovered_server, recovered_thread)


def main() -> None:
    result = asyncio.run(verify())
    print(json.dumps(result, ensure_ascii=False))
    if not all(result.values()):
        raise SystemExit("La recuperación offline no cumplió todas las garantías.")


if __name__ == "__main__":
    main()
