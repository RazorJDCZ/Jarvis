from __future__ import annotations

import asyncio
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jarvis.actions.browser import ControlledBrowser
from jarvis.config import Settings


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


async def verify(base_url: str) -> dict[str, object]:
    settings = Settings()
    browser = ControlledBrowser(settings.data_dir, settings.browser_search_url)
    try:
        status = await browser.status()
        opened = await browser.open(f"{base_url}/automation.html", "chrome")
        launch_arguments = [str(value) for value in browser._process.args]
        await browser._context.clear_cookies(name="jarvis_profile_smoke")
        await browser._page.evaluate("localStorage.removeItem('jarvis_profile_smoke')")
        await browser._page.evaluate("localStorage.setItem('jarvis_profile_smoke', 'persistent')")
        await browser._context.add_cookies(
            [
                {
                    "name": "jarvis_profile_smoke",
                    "value": "persistent",
                    "url": base_url,
                    "expires": time.time() + 3600,
                }
            ]
        )
        immediate_cookies = await browser._context.cookies(base_url)
        await browser._page.wait_for_timeout(800)
        filled = await browser.fill("Nombre", "JARVIS_BROWSER_SMOKE")
        input_value = await browser._page.get_by_label("Nombre").input_value()
        clicked = await browser.click("Activar prueba")
        read = await browser.read()
        opened_result = await browser.open_result(1)
        new_tab = await browser.new_tab()
        tabs_before_close = await browser.list_tabs()
        closed = await browser.close_tab()
        tabs_after_close = await browser.list_tabs()
        edge_opened = None
        if "edge" in status.details.get("installed_browsers", []):
            edge_opened = await browser.open(f"{base_url}/automation.html", "edge")
        else:
            await browser.close()
        reopened_chrome = await browser.open(f"{base_url}/automation.html", "chrome")
        persisted_cookies = await browser._context.cookies(base_url)
        profile_persisted = reopened_chrome.success and any(
            cookie["name"] == "jarvis_profile_smoke" and cookie["value"] == "persistent"
            for cookie in persisted_cookies
        )
        await browser._context.clear_cookies(name="jarvis_profile_smoke")
        await browser._page.evaluate("localStorage.removeItem('jarvis_profile_smoke')")
        return {
            "chrome_available": "chrome" in status.details.get("installed_browsers", []),
            "chrome_opened": opened.success
            and opened.details.get("verified") is True
            and opened.details.get("browser") == "chrome",
            "normal_window": "--new-window" in launch_arguments
            and "--incognito" not in launch_arguments
            and "--inprivate" not in launch_arguments,
            "profile_persisted": profile_persisted,
            "profile_cookie_created": any(
                cookie["name"] == "jarvis_profile_smoke" and cookie["value"] == "persistent"
                for cookie in immediate_cookies
            ),
            "filled": filled.success and input_value == "JARVIS_BROWSER_SMOKE",
            "clicked": clicked.success and "Acción verificada" in read.message,
            "opened_result": opened_result.success
            and "result.html" in opened_result.details["url"],
            "new_tab": new_tab.success,
            "tabs_before_close": len(tabs_before_close.details.get("tabs", [])),
            "closed_tab": closed.success,
            "tabs_after_close": len(tabs_after_close.details.get("tabs", [])),
            "edge_switch": edge_opened is None
            or (
                edge_opened.success
                and edge_opened.details.get("browser") == "edge"
                and edge_opened.details.get("verified") is True
            ),
        }
    finally:
        await browser.close()


def main() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    handler = partial(QuietHandler, directory=str(fixture_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        result = asyncio.run(verify(f"http://{host}:{port}"))
        print(json.dumps(result, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
