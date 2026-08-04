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
    path = Path(tempfile.mkdtemp(prefix="jarvis-remote-smoke-"))
    try:
        yield path
    finally:
        for attempt in range(20):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)


async def verify() -> dict[str, object]:
    port = free_port()
    with temporary_project() as project_root:
        origin = f"http://localhost:{port}"
        settings = Settings(
            project_root=project_root,
            port=port,
            brain_mode="fallback",
            action_model_planning=False,
            memory_enabled=False,
            remote_access_enabled=True,
            remote_origin=origin,
            remote_allowed_login="owner@example.com",
        )
        app = create_app(settings)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                log_level="error",
            )
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("El servidor de prueba no inició.")

        pairing = app.state.remote_access.start_pairing()
        page_errors: list[str] = []
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="chrome", headless=True)
                context = await browser.new_context(
                    service_workers="block",
                    viewport={"width": 390, "height": 844},
                    extra_http_headers={
                        "Tailscale-User-Login": "owner@example.com",
                        "Tailscale-User-Name": "Owner",
                    }
                )
                page = await context.new_page()
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                cdp = await context.new_cdp_session(page)
                await cdp.send("WebAuthn.enable")
                authenticator = await cdp.send(
                    "WebAuthn.addVirtualAuthenticator",
                    {
                        "options": {
                            "protocol": "ctap2",
                            "ctap2Version": "ctap2_1",
                            "transport": "internal",
                            "hasResidentKey": True,
                            "hasUserVerification": True,
                            "isUserVerified": True,
                            "automaticPresenceSimulation": True,
                        }
                    },
                )

                await page.goto(origin)
                await page.locator("#remoteGate").wait_for(state="visible")
                await page.locator("#remoteDeviceLabel").fill("Teléfono virtual")
                await page.locator("#remotePairingCode").fill(pairing["code"])
                await page.locator('#remotePairingForm button[type="submit"]').click()
                try:
                    await page.locator("#remoteGate").wait_for(state="hidden", timeout=10_000)
                except Exception as exc:
                    gate_error = await page.locator("#remoteGateError").inner_text()
                    raise RuntimeError(
                        f"El emparejamiento visual falló: {gate_error}; JS={page_errors}"
                    ) from exc
                paired = not await page.locator("#emergencyStopButton").is_hidden()
                no_horizontal_overflow = await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )

                await page.locator("#textInput").fill("abre la calculadora")
                await page.locator("#textForm button").click()
                await page.locator("#actionConfirmation").wait_for(state="visible")
                elevated = "Autorizar desde el celular" in await page.locator(
                    "#actionDescription"
                ).inner_text()

                await context.clear_cookies()
                await page.reload()
                await page.locator("#authenticateRemoteButton").wait_for(state="visible")
                await page.locator("#authenticateRemoteButton").click()
                await page.locator("#remoteGate").wait_for(state="hidden")
                await page.locator("#actionConfirmation").wait_for(state="visible")
                restored = await page.locator("#actionConfirmation").is_visible()

                await page.locator("#emergencyStopButton").click()
                await page.locator("#actionConfirmation").wait_for(state="hidden")
                await page.get_by_text("Parada remota completada", exact=False).wait_for(
                    state="visible"
                )
                stopped = not await page.locator("#actionConfirmation").is_visible()

                credentials = await cdp.send(
                    "WebAuthn.getCredentials",
                    {"authenticatorId": authenticator["authenticatorId"]},
                )
                await browser.close()
                return {
                    "paired_with_real_webauthn": paired and len(credentials["credentials"]) == 1,
                    "remote_mutation_escalated": elevated,
                    "reauthenticated_with_passkey": restored,
                    "pending_action_restored": restored,
                    "emergency_stop_cancelled_pending": stopped,
                    "mobile_layout_no_horizontal_overflow": no_horizontal_overflow,
                    "page_errors": page_errors,
                }
        finally:
            server.should_exit = True
            server_thread.join(timeout=10)
            if server_thread.is_alive():
                server.force_exit = True
                server_thread.join(timeout=5)
            time.sleep(0.2)


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
