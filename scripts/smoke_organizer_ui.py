"""Synthetic browser acceptance tests for the organizer and the built Appa UI."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright

from jarvis.config import PROJECT_ROOT, Settings
from jarvis.main import create_app


async def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="jarvis-organizer-ui-") as folder:
        config = Settings(
            project_root=Path(folder),
            port=port,
            brain_mode="fallback",
            voice_preload=False,
            adaptive_resources=False,
            semantic_enabled=False,
            appa_auto_discover=False,
            safe_actions_enabled=False,
            memory_enabled=False,
        )
        app = create_app(config)
        organizer = app.state.organizer
        organizer.refresh = AsyncMock()
        app.state.mail.sync = AsyncMock()
        organizer.calendar.publish = AsyncMock(
            return_value={
                "id": "synthetic",
                "calendar_id": "fixture",
                "url": "https://calendar.google.com/",
                "etag": "one",
            }
        )
        editable_event = {
            "id": "fixture:editable",
            "calendar_id": "fixture",
            "event_id": "editable",
            "title": "Reunión editable",
            "description": "Original",
            "start_at": (datetime.now().astimezone() + timedelta(days=1))
            .replace(hour=10, minute=0, second=0, microsecond=0)
            .isoformat(),
            "end_at": (datetime.now().astimezone() + timedelta(days=1))
            .replace(hour=11, minute=0, second=0, microsecond=0)
            .isoformat(),
            "all_day": False,
            "busy": True,
            "source": "Google Calendar",
            "url": "https://calendar.google.com/",
            "calendar": "Jarvis",
            "etag": '"one"',
            "reminders": [60],
            "editable": True,
        }
        organizer.store.put("google_event", editable_event["id"], editable_event)
        organizer.edit_google_event = AsyncMock(
            return_value={**editable_event, "title": "Reunión actualizada", "etag": '"two"'}
        )
        account = app.state.mail.store.connect("microsoft", "student@example.com", {})
        app.state.mail.store.ingest(
            account,
            {
                "thread_id": "one",
                "version": "one",
                "subject": "Examen sintético",
                "sender": "Profesor",
                "received": datetime.now().astimezone().isoformat(),
                "body": "Examen el 28 de septiembre de 2026 a las 15:00",
                "url": "https://outlook.office.com/mail/",
            },
        )
        item = app.state.mail.store.list()[0]
        app.state.mail.store.update(item["id"], deadline="28 de septiembre de 2026 a las 15:00")
        organizer.store.put(
            "meta",
            "appa",
            {
                "tasks": [
                    {
                        "id": "one",
                        "title": "Informe sintético",
                        "due": "2026-09-28",
                        "completed": False,
                    }
                ],
                "events": [],
                "synced": 1,
                "error": "",
            },
        )
        app.state.transcriber.transcribe = AsyncMock(return_value=("Mi idea dictada", "es"))
        dist = PROJECT_ROOT.parent / "appa" / "dist"
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="appa-assets")

        @app.get("/appa-ui")
        async def appa_page():
            return FileResponse(dist / "index.html")

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            await asyncio.sleep(0.05)
        errors = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel="chrome", headless=True)
                context = await browser.new_context(viewport={"width": 1440, "height": 960})
                await context.add_init_script("""
                    window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {unregisterListener: () => {}};
                    window.__TAURI_INTERNALS__ = {
                      transformCallback: () => 1, unregisterCallback: () => {},
                      invoke: async (cmd, args = {}) => {
                        if (cmd.startsWith('plugin:event|')) return 1;
                        if (cmd === 'organizer_request') {
                          const map = {today:['GET','today'], refresh:['POST','refresh'],
                            capture:['POST','captures'], study:['POST','study'],
                            complete:['DELETE',`captures/${args.id}`],
                            publish:['POST',`proposals/${args.id}/publish`],
                            event_update:['PATCH','calendar/events'],
                            dismiss:['DELETE',`proposals/${args.id}`], backup:['POST','backups']};
                          const [method,path] = map[args.operation];
                          const response = await fetch('/api/organizer/'+path,{method,
                            headers:{'Content-Type':'application/json'},
                            ...(method==='GET'?{}:{body:JSON.stringify(args.payload)})});
                          const data = await response.json();
                          if(!response.ok) throw new Error(data.detail);
                          return data;
                        }
                        if (cmd.includes('system_metrics')) throw new Error('Synthetic UI test');
                        return [];
                      }
                    };
                """)
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                base = f"http://127.0.0.1:{port}"
                await page.goto(base + "/appa-ui")
                await page.get_by_text("Dashboard", exact=True).first.wait_for()
                await page.evaluate(
                    "window.dispatchEvent(new CustomEvent('appa-route', {detail:'today'}))"
                )
                await page.get_by_role("heading", name="Hoy", exact=True).wait_for()
                await page.get_by_text("Reunión editable", exact=False).first.wait_for()
                await page.get_by_role("button", name="Editar", exact=True).click()
                event_dialog = page.get_by_role("dialog", name="Editar evento de Jarvis")
                await event_dialog.get_by_label("Título").fill("Reunión actualizada")
                await event_dialog.get_by_role("button", name="Guardar cambios", exact=True).click()
                await page.get_by_text(
                    "Evento actualizado en el calendario Jarvis.", exact=True
                ).wait_for()
                organizer.edit_google_event.assert_awaited_once()
                await page.get_by_label("Idea o pendiente").fill("Idea desde Appa")
                await page.get_by_role("button", name="Guardar", exact=True).click()
                await page.get_by_text("Idea desde Appa", exact=True).wait_for()
                await page.get_by_label("Título del evento").fill("Examen revisado")
                await page.get_by_role("button", name="Guardar en Calendar", exact=True).click()
                await page.get_by_text("Evento guardado en Google Calendar.", exact=True).wait_for()
                organizer.calendar.publish.assert_awaited_once()
                await page.get_by_label("Materia o entrega").fill("Cálculo")
                await page.get_by_label("Fecha límite").fill(
                    (datetime.now().date() + timedelta(days=10)).isoformat()
                )
                await page.get_by_role("button", name="Proponer sesiones").click()
                await page.get_by_role(
                    "heading", name="Estudiar: Cálculo", exact=True
                ).first.wait_for()
                await page.screenshot(path=str(PROJECT_ROOT / ".data" / "organizer-appa.png"))
                await page.goto(base + "/organizer")
                await page.get_by_text("Idea desde Appa", exact=False).first.wait_for()
                await page.locator("#capture textarea").fill("Idea móvil")
                await page.locator(
                    "#capture button[type=submit], #capture button:not([type])"
                ).click()
                await page.get_by_text("Captura guardada.", exact=True).wait_for()
                await page.evaluate("navigator.serviceWorker.ready")
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.screenshot(path=str(PROJECT_ROOT / ".data" / "organizer-mobile.png"))
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                await context.set_offline(True)
                await page.reload()
                await page.locator("#capture textarea").fill("Idea sin red")
                await page.locator("#capture button:not([type])").click()
                await page.get_by_text(
                    "Guardado en este dispositivo; pendiente de sincronizar con Jarvis.", exact=True
                ).wait_for()
                await context.set_offline(False)
                await page.reload()
                await page.get_by_text("Idea sin red", exact=False).first.wait_for()
                await page.wait_for_function(
                    "JSON.parse(localStorage.getItem('jarvis-quick-captures-v1')"
                    " || '[]').length === 0"
                )
                assert (
                    len([c for c in organizer.store.list("capture") if c["text"] == "Idea sin red"])
                    == 1
                )
                response = await context.request.post(
                    base + "/api/organizer/transcribe",
                    multipart={
                        "audio": {
                            "name": "synthetic.webm",
                            "mimeType": "audio/webm",
                            "buffer": b"synthetic",
                        }
                    },
                )
                assert (await response.json())["text"] == "Mi idea dictada"
                assert not errors, errors
                await browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        print(
            json.dumps(
                {
                    "appa_today": "passed",
                    "mail_event_review": "passed",
                    "managed_event_edit": "passed",
                    "study": "passed",
                    "capture_offline": "passed",
                    "transcription_route": "passed",
                    "browser_errors": errors,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
