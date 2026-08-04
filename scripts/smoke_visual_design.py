from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

from jarvis.config import Settings
from jarvis.main import create_app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def verify() -> dict[str, object]:
    port = free_port()
    output = Settings().data_dir / "tmp"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-visual-smoke-") as project:
        app = create_app(
            Settings(
                project_root=Path(project),
                port=port,
                brain_mode="fallback",
                action_model_planning=False,
                memory_enabled=False,
            )
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
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
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("El servidor visual de prueba no inició")

        errors: list[str] = []
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome", headless=True)
                context = await browser.new_context(
                    service_workers="block",
                    viewport={"width": 1600, "height": 1000},
                )
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"http://127.0.0.1:{port}")
                await page.locator("#textInput").wait_for(state="visible")
                await page.wait_for_timeout(700)
                desktop_path = output / "jarvis-red-spider-desktop.png"
                await page.screenshot(path=desktop_path)
                desktop_overflow = await page.evaluate(
                    "document.documentElement.scrollWidth > window.innerWidth"
                )
                palette = await page.evaluate(
                    """() => {
                      const style = getComputedStyle(document.documentElement);
                      return [style.getPropertyValue('--primary').trim(),
                              style.getPropertyValue('--secondary').trim()];
                    }"""
                )
                eyebrow = await page.locator(".eyebrow").inner_text()
                spiders = await page.locator(".spider-mark").count()

                await page.set_viewport_size({"width": 390, "height": 844})
                await page.wait_for_timeout(500)
                mobile_path = output / "jarvis-red-spider-mobile.png"
                await page.screenshot(path=mobile_path)
                mobile_overflow = await page.evaluate(
                    "document.documentElement.scrollWidth > window.innerWidth"
                )
                await browser.close()
                return {
                    "palette": palette,
                    "eyebrow": eyebrow,
                    "spider_marks": spiders,
                    "desktop_no_horizontal_overflow": not desktop_overflow,
                    "mobile_no_horizontal_overflow": not mobile_overflow,
                    "page_errors": errors,
                    "desktop_screenshot": str(desktop_path),
                    "mobile_screenshot": str(mobile_path),
                }
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
