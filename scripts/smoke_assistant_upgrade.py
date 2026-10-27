from __future__ import annotations

import asyncio
import io
import json
import socket
import tempfile
import threading
import wave
from pathlib import Path
from unittest.mock import AsyncMock

import uvicorn
from playwright.async_api import async_playwright

from jarvis.config import PROJECT_ROOT, Settings
from jarvis.main import create_app
from jarvis.schemas import ProviderStatus
from jarvis.services.memory import MemoryCandidate
from jarvis.services.performance import token_sink


async def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="jarvis-assistant-ui-") as directory:
        settings = Settings(
            project_root=Path(directory),
            port=port,
            brain_mode="fallback",
            action_model_planning=False,
            safe_actions_enabled=False,
            appa_auto_discover=False,
            voice_preload=False,
            adaptive_resources=False,
            semantic_enabled=False,
            stt_device="cpu",
            file_search_roots=directory,
        )
        app = create_app(settings)
        app.state.conversation.verifier.verify = AsyncMock(return_value=None)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes(bytes(8000))
        app.state.tts.status = AsyncMock(
            return_value=ProviderStatus(
                available=True,
                name="Test voice",
                detail="Synthetic audio",
            )
        )
        app.state.tts.synthesize = AsyncMock(return_value=audio.getvalue())
        app.state.transcriber.transcribe = AsyncMock(return_value=("Dime la hora", "es"))
        app.state.conversation.memory.store.upsert(
            MemoryCandidate("color", "Prefiere azul", "preference")
        )

        async def fake_chat(messages):
            sink = token_sink.get()
            if sink:
                await sink("Primera frase visible. ")
            await asyncio.sleep(1.5)
            if sink:
                await sink("Respuesta terminada.")
            return "Primera frase visible. Respuesta terminada."

        app.state.conversation.brain.chat = fake_chat

        @app.post("/api/test/hanging-stream")
        async def hanging_stream():
            await asyncio.sleep(30)
            return {"status": "unexpected"}

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        errors = []
        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    channel="chrome", headless=True, args=["--mute-audio"]
                )
                for label, viewport in (
                    ("desktop", {"width": 1440, "height": 1000}),
                    ("mobile", {"width": 390, "height": 844}),
                ):
                    context = await browser.new_context(viewport=viewport, service_workers="block")
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(f"http://127.0.0.1:{port}")
                    await page.wait_for_function("() => appState.initialized")
                    await page.locator("#muteButton").click()
                    await page.locator("#textInput").fill("Conversa conmigo acerca de descansar")
                    await page.locator('#textForm button[type="submit"]').click()
                    await page.get_by_text("Primera frase visible.", exact=True).wait_for(
                        timeout=10000
                    )
                    assert await page.evaluate("appState.streaming")
                    await page.get_by_text(
                        "Primera frase visible. Respuesta terminada.", exact=True
                    ).wait_for()
                    await page.wait_for_function("() => !appState.busy")
                    assert await page.locator(".jarvis-message").count() == 2
                    await page.locator("#muteButton").click()
                    await page.locator("#textInput").fill("Conversa conmigo acerca de descansar")
                    await page.locator('#textForm button[type="submit"]').click()
                    await page.wait_for_function("() => appState.speaking && appState.streaming")
                    await page.wait_for_function("() => !appState.busy")
                    timing = await page.evaluate("appState.lastTiming")
                    assert timing["first_audio_ms"] < timing["response_ms"], timing
                    await page.evaluate(
                        "sendUtterance(encodeWav(new Float32Array(16000), 16000), false)"
                    )
                    assert await page.get_by_text("Dime la hora", exact=True).count() == 1
                    await page.locator("#muteButton").click()
                    await page.evaluate("openControlDeck('assistant')")
                    await page.get_by_text("Tu asistente cotidiano", exact=True).wait_for()
                    await page.locator(".assistant-search input").fill("proyecto atlas")
                    await page.locator('.assistant-search button[type="submit"]').click()
                    await page.wait_for_function(
                        "() => document.querySelector('.assistant-search-results')"
                        "?.textContent.trim()"
                    )
                    await page.get_by_role(
                        "button", name="Permisos y seguridad", exact=True
                    ).click()
                    await page.get_by_text(
                        "La busqueda de archivos es solo lectura", exact=False
                    ).wait_for()
                    await page.get_by_role(
                        "button", name="Automatizaciones proactivas", exact=True
                    ).click()
                    await page.wait_for_function(
                        "() => document.querySelectorAll('.automation-edit-row').length === 5"
                    )
                    await page.get_by_text("Cola fiable:", exact=False).wait_for()
                    await page.get_by_role(
                        "button", name="Ver y corregir memoria", exact=True
                    ).click()
                    await page.locator(".memory-edit-row textarea").fill("Prefiere verde")
                    await page.get_by_role("button", name="Guardar corrección", exact=True).click()
                    await page.wait_for_function(
                        "() => document.querySelector('.memory-edit-row textarea')?.value "
                        "=== 'Prefiere verde'"
                    )
                    await page.select_option('select[name="compact"]', "true")
                    assert await page.locator("body").evaluate(
                        "el => el.classList.contains('compact-mode')"
                    )
                    await page.get_by_role(
                        "button", name="Diagnosticar conexión y respuesta", exact=True
                    ).click()
                    await page.get_by_text("Consulta al servidor:", exact=False).wait_for()
                    await page.screenshot(path=str(PROJECT_ROOT / ".data" / f"upgrade-{label}.png"))
                    await page.evaluate("closeControlDeck()")
                    await page.locator("#textInput").fill("Conversa conmigo acerca de descansar")
                    await page.locator('#textForm button[type="submit"]').click()
                    await page.wait_for_function("() => appState.streaming")
                    await page.evaluate("cancelActiveClientWork(); stopSpeaking()")
                    await page.wait_for_function("() => !appState.busy && !appState.streaming")
                    timeout_recovery = await page.evaluate(
                        """async () => {
                          appState.busy = true;
                          try {
                            await receiveAssistantStream(
                              "/api/test/hanging-stream",
                              { method: "POST" },
                              80,
                            );
                            return { recovered: false, message: "" };
                          } catch (error) {
                            return {
                              recovered: !appState.busy && !appState.streaming,
                              message: error.message,
                            };
                          }
                        }"""
                    )
                    assert timeout_recovery["recovered"]
                    assert "volver a hablar" in timeout_recovery["message"]
                    results.append(
                        {
                            "viewport": label,
                            "streaming": True,
                            "memory_edit": True,
                            "personal_search": True,
                            "security_summary": True,
                            "automation_queue": True,
                            "settings": True,
                            "cancellation": True,
                            "timeout_recovery": True,
                        }
                    )
                    await context.close()
                await browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert not errors, errors
        print(json.dumps({"results": results, "browser_errors": errors}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
