from __future__ import annotations

import asyncio
import json
import threading
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
        opened = await browser.open(f"{base_url}/automation.html")
        filled = await browser.fill("Nombre", "JARVIS_BROWSER_SMOKE")
        input_value = await browser._page.get_by_label("Nombre").input_value()
        clicked = await browser.click("Activar prueba")
        read = await browser.read()
        opened_result = await browser.open_result(1)
        new_tab = await browser.new_tab()
        tabs_before_close = await browser.list_tabs()
        closed = await browser.close_tab()
        tabs_after_close = await browser.list_tabs()
        return {
            "opened": opened.success and opened.details.get("verified") is True,
            "filled": filled.success and input_value == "JARVIS_BROWSER_SMOKE",
            "clicked": clicked.success and "Acción verificada" in read.message,
            "opened_result": opened_result.success
            and "result.html" in opened_result.details["url"],
            "new_tab": new_tab.success,
            "tabs_before_close": len(tabs_before_close.details.get("tabs", [])),
            "closed_tab": closed.success,
            "tabs_after_close": len(tabs_after_close.details.get("tabs", [])),
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
