from __future__ import annotations

import asyncio
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jarvis.actions.browser import ControlledBrowser
from jarvis.actions.vision import LocalVisionController
from jarvis.actions.windows import DesktopInputController, WindowController
from jarvis.config import Settings


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


async def verify(base_url: str) -> dict[str, object]:
    settings = Settings()
    browser = ControlledBrowser(settings.data_dir, settings.browser_search_url)
    vision = LocalVisionController(settings)
    try:
        opened = await browser.open(f"{base_url}/automation.html")
        window = WindowController()
        maximized = await asyncio.to_thread(
            window.change_state,
            "maximize",
            "Banco de pruebas Etapa 2",
        )
        await asyncio.sleep(0.5)
        status = await vision.status()
        located = await vision.find("el botón azul ACTIVAR PRUEBA VISUAL")
        clicked = False
        verified = False
        actual_rectangle = await browser._page.locator("#activate").evaluate(
            """element => {
              const rect = element.getBoundingClientRect();
              const borderX = (window.outerWidth - window.innerWidth) / 2;
              const chromeY = window.outerHeight - window.innerHeight;
              return {
                left: window.screenX + borderX + rect.left,
                top: window.screenY + chromeY + rect.top,
                right: window.screenX + borderX + rect.right,
                bottom: window.screenY + chromeY + rect.bottom,
                devicePixelRatio: window.devicePixelRatio,
              };
            }"""
        )
        inside_control = bool(
            located.success
            and actual_rectangle
            and actual_rectangle["left"] <= located.details["x"] <= actual_rectangle["right"]
            and actual_rectangle["top"] <= located.details["y"] <= actual_rectangle["bottom"]
        )
        if located.success and located.details.get("dangerous") is not True and inside_control:
            result = await asyncio.to_thread(
                DesktopInputController().click,
                located.details["x"],
                located.details["y"],
            )
            clicked = result.success
            if clicked:
                try:
                    await browser._page.get_by_text("Acción verificada", exact=True).wait_for(
                        timeout=5_000
                    )
                    verified = True
                except Exception:
                    verified = False
        return {
            "opened": opened.success,
            "maximized": maximized.success,
            "vision_available": status.success,
            "vision_located": located.success,
            "locate_error": None if located.success else located.message,
            "confidence": located.details.get("confidence"),
            "safe_target": located.details.get("dangerous") is False,
            "model_coordinates": [located.details.get("x"), located.details.get("y")],
            "actual_rectangle": actual_rectangle,
            "coordinate_inside_control": inside_control,
            "pixel_clicked": clicked,
            "effect_verified": verified,
            "capture_persisted": False,
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
        time.sleep(0.2)


if __name__ == "__main__":
    main()
