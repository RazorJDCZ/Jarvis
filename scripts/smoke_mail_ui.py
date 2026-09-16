"""Exercise built Appa UI and Jarvis mail API with isolated, synthetic data only."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright

from jarvis.config import PROJECT_ROOT, Settings
from jarvis.main import create_app


async def main():
    dist = PROJECT_ROOT.parent / "appa" / "dist"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="jarvis-mail-ui-") as folder:
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
        mail = app.state.mail
        mail.sync = AsyncMock()
        mail.summarize_one = AsyncMock()
        mail._generate = AsyncMock(return_value="Hola, revisaré la documentación. [completar]")
        connector = SimpleNamespace(
            _require_capabilities=AsyncMock(),
            _request=AsyncMock(return_value={}),
            _json=lambda r: r,
            _decode=lambda r: SimpleNamespace(task_id="test-task"),
        )
        mail.capabilities = SimpleNamespace(
            connectors=SimpleNamespace(require_appa=lambda: connector)
        )
        identifier = mail.store.connect(
            "microsoft", "estudiante@universidad.example", {"test": True}
        )
        mail.store.account_result(identifier, synced=time.time())
        mail.store.ingest(
            identifier,
            {
                "thread_id": "thread1",
                "version": "v1",
                "subject": "Entrega del informe",
                "sender": "Docente",
                "received": "2026-09-15T12:00:00+00:00",
                "url": "https://outlook.office.com/mail/",
                "body": "Entregar informe antes del viernes.",
            },
        )
        item = mail.store.list()[0]
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="appa-assets")

        @app.get("/appa-ui")
        async def appa_page():
            return FileResponse(dist / "index.html")

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
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
                        if (cmd === 'mail_request') {
                          const map = {status:['GET','status'],
                            list:['GET','items?include_resolved=true'],
                            sync:['POST','sync'], update:['PATCH',`items/${args.id}`],
                            task:['POST',`items/${args.id}/task`],
                            draft:['POST',`items/${args.id}/draft`]};
                          const [method,path] = map[args.operation];
                          const response = await fetch('/api/mail/'+path, {method,
                            headers:{'Content-Type':'application/json'},
                            ...(method==='GET'?{}:{body:JSON.stringify(args.payload)})});
                          const result = await response.json();
                          if (!response.ok) throw new Error(result.detail);
                          return result;
                        }
                        if (cmd.includes('system_metrics')) throw new Error('Synthetic UI test');
                        return [];
                      }
                    };
                """)
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"http://127.0.0.1:{port}/appa-ui")
                await page.get_by_text("Correos Pendientes", exact=True).wait_for()
                await page.evaluate(
                    "window.dispatchEvent(new CustomEvent('appa-route', {detail:'mail'}))"
                )
                await page.get_by_role("heading", name="Entrega del informe", exact=True).wait_for()
                await page.get_by_role("button", name="Crear tarea", exact=True).click()
                await (
                    page.get_by_role("dialog")
                    .get_by_role("button", name="Crear tarea", exact=True)
                    .click()
                )
                await page.get_by_role("button", name="Tarea vinculada", exact=True).wait_for()
                connector._request.assert_awaited_once()
                await page.get_by_role("button", name="Preparar borrador", exact=True).click()
                await page.get_by_role("textbox", name="Borrador: Entrega del informe").fill(
                    "Texto revisado por mí."
                )
                await page.get_by_role("button", name="Guardar borrador", exact=True).click()
                await page.get_by_text("Borrador guardado localmente.", exact=True).wait_for()
                assert mail.store.get(item["id"])["draft"] == "Texto revisado por mí."
                await page.get_by_role("button", name="Posponer 24 h", exact=True).click()
                await page.get_by_role("heading", name="No hay correos en esta vista").wait_for()
                await page.get_by_label("Estado de correos", exact=True).select_option("snoozed")
                await page.get_by_role("heading", name="Entrega del informe").wait_for()
                await page.get_by_role("button", name="Quitar posposición").click()
                await page.get_by_label("Estado de correos", exact=True).select_option("pending")
                await page.get_by_role("heading", name="Entrega del informe").wait_for()
                await page.screenshot(path=str(PROJECT_ROOT / ".data" / "mail-appa-desktop.png"))
                await page.get_by_label("Estado: Entrega del informe", exact=True).select_option(
                    "resolved"
                )
                await page.get_by_role("heading", name="No hay correos en esta vista").wait_for()
                await page.reload()
                await page.get_by_text("Correos Pendientes", exact=True).wait_for()
                await page.evaluate(
                    "window.dispatchEvent(new CustomEvent('appa-route', {detail:'mail'}))"
                )
                await page.get_by_label("Estado de correos", exact=True).select_option("resolved")
                await page.get_by_role("heading", name="Entrega del informe").wait_for()
                await page.goto(f"http://127.0.0.1:{port}/mail")
                await page.locator('form[data-provider="google"] input[name="client_id"]').fill(
                    "test123.apps.googleusercontent.com"
                )
                await page.get_by_role(
                    "button", name="Guardar conexión de Gmail", exact=True
                ).click()
                await page.get_by_text(
                    "Configuración guardada. Ya puedes conectar la cuenta.", exact=True
                ).wait_for()
                assert await page.get_by_role(
                    "button", name="Conectar Gmail", exact=True
                ).is_enabled()
                await page.screenshot(path=str(PROJECT_ROOT / ".data" / "mail-setup-desktop.png"))
                assert not errors, errors
                await browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        print(
            json.dumps(
                {
                    "mail_ui": "passed",
                    "task": "idempotent",
                    "draft_edit": "persisted",
                    "snooze": "passed",
                    "state_reload": "passed",
                    "oauth_setup": "passed",
                    "browser_errors": errors,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
