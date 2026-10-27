from __future__ import annotations

import asyncio
import json

from jarvis.actions.browser import ControlledBrowser
from jarvis.config import Settings


async def verify() -> dict[str, object]:
    settings = Settings()
    browser = ControlledBrowser(settings.data_dir, settings.browser_search_url)
    try:
        opened = await browser.open(f"http://{settings.host}:{settings.port}")
        page = browser._page
        await page.locator("#textInput").wait_for(state="visible", timeout=15_000)
        await page.locator("#muteButton").click()
        await page.locator("#actionsStatus.online").wait_for(state="visible", timeout=15_000)
        await page.locator("#visionStatus.online").wait_for(state="visible", timeout=15_000)

        # Local medium-risk actions are direct; high-risk pixel clicks must still gate.
        await page.locator("#textInput").fill("haz clic en 400, 250")
        await page.locator('#textForm button[type="submit"]').click()
        gate = page.locator("#actionConfirmation")
        await gate.wait_for(state="visible", timeout=15_000)
        gate_text = await gate.inner_text()

        await page.locator("#rejectActionButton").click()
        await gate.wait_for(state="hidden", timeout=15_000)
        await page.get_by_text("Acción cancelada", exact=False).wait_for(
            state="visible", timeout=15_000
        )

        await page.locator("#textInput").fill("estado del sistema")
        await page.locator('#textForm button[type="submit"]').click()
        await page.get_by_text("CPU", exact=False).last.wait_for(state="visible", timeout=15_000)
        await page.evaluate(
            """handleAction({
              action_id: "dialog-smoke",
              name: "dialog.choose",
              risk: "medium",
              description: "Responder al diálogo Bloc de notas",
              requires_confirmation: true,
              details: {dialog_options: ["Guardar", "No guardar", "Cancelar"]},
            })"""
        )
        dialog_buttons = page.locator("#dialogChoiceButtons button")
        await dialog_buttons.first.wait_for(state="visible", timeout=5_000)
        dialog_labels = await dialog_buttons.all_text_contents()
        regular_buttons_hidden = await page.locator("#approveActionButton").is_hidden()
        await page.evaluate("handleAction(null)")
        idle_animation_before = await page.locator(".orbit-one").evaluate(
            "element => getComputedStyle(element).transform"
        )
        await page.wait_for_timeout(450)
        idle_animation_after = await page.locator(".orbit-one").evaluate(
            "element => getComputedStyle(element).transform"
        )
        voice_privacy = await page.evaluate(
            """() => {
              const fakeAudio = {
                paused: false,
                pause() { this.paused = true; },
                play() { this.paused = false; return Promise.resolve(); },
              };
              appState.speaking = true;
              appState.busy = true;
              appState.audioPlayer = fakeAudio;
              microphone.ready = true;
              microphone.handsFree = false;
              microphone.manual = false;
              microphone.capturing = false;
              microphone.interruptionCapture = false;
              microphone.preRoll = [];
              microphone.preRollSamples = 0;
              microphone.threshold = 0.016;
              microphone.context = {sampleRate: 16000, state: "closed"};
              microphone.process(new Float32Array(2048).fill(0.08));
              const ambientOff = {
                capturing: microphone.capturing,
                interruptionCapture: microphone.interruptionCapture,
                playbackPaused: fakeAudio.paused,
                statePaused: appState.interruptionPaused,
              };

              microphone.handsFree = true;
              microphone.process(new Float32Array(2048).fill(0.08));
              const ambientOn = {
                capturing: microphone.capturing,
                interruptionCapture: microphone.interruptionCapture,
                playbackPaused: fakeAudio.paused,
                statePaused: appState.interruptionPaused,
              };
              microphone.disableHandsFree();

              let trackStopped = false;
              let contextClosed = false;
              microphone.ready = true;
              microphone.handsFree = false;
              microphone.stream = {getTracks: () => [{stop() { trackStopped = true; }}]};
              microphone.context = {
                state: "running",
                close() { contextClosed = true; this.state = "closed"; return Promise.resolve(); },
              };
              microphone.cancelManual();
              const released = {
                trackStopped,
                contextClosed,
                ready: microphone.ready,
                streamCleared: microphone.stream === null,
              };

              appState.audioPlayer = null;
              stopSpeaking();
              return {
                ambientOff,
                ambientOn,
                released,
                mobileBridge: typeof window.jarvisMobileVoice?.start === "function"
                  && typeof window.jarvisMobileVoice?.stop === "function"
                  && typeof window.jarvisMobileVoice?.cancel === "function",
              };
            }"""
        )
        await page.locator("#mobileAccessButton").click()
        await page.locator("#mobileAccessDialog").wait_for(state="visible")
        remote_enabled = await page.evaluate(
            "fetch('/api/remote/status').then(response => response.json())"
            ".then(data => data.enabled)"
        )
        pairing_disabled = await page.locator("#createPairingButton").is_disabled()
        mobile_admin_ready = (
            "TAILNET LINK" in await page.locator("#remoteAdminState").inner_text()
            and pairing_disabled != remote_enabled
        )
        await page.locator("#closeMobileAccessButton").click()
        return {
            "ui_opened": opened.success,
            "actions_online": await page.locator("#actionsStatus").evaluate(
                "element => element.classList.contains('online')"
            ),
            "vision_online": await page.locator("#visionStatus").evaluate(
                "element => element.classList.contains('online')"
            ),
            "security_gate": "RIESGO MEDIO" in gate_text,
            "cancelled_without_execution": not await gate.is_visible(),
            "system_action_response": True,
            "dialog_options_rendered": dialog_labels == ["Guardar", "No guardar", "Cancelar"],
            "ambiguous_confirm_hidden": regular_buttons_hidden,
            "idle_core_is_animated": idle_animation_before != idle_animation_after,
            "ambient_off_does_not_listen": voice_privacy["ambientOff"]
            == {
                "capturing": False,
                "interruptionCapture": False,
                "playbackPaused": False,
                "statePaused": False,
            },
            "ambient_mode_can_interrupt": voice_privacy["ambientOn"]
            == {
                "capturing": True,
                "interruptionCapture": True,
                "playbackPaused": True,
                "statePaused": True,
            },
            "push_to_talk_releases_microphone": voice_privacy["released"]
            == {
                "trackStopped": True,
                "contextClosed": True,
                "ready": False,
                "streamCleared": True,
            },
            "mobile_voice_bridge_ready": voice_privacy["mobileBridge"],
            "mobile_access_admin_ready": mobile_admin_ready,
        }
    finally:
        await browser.close()


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
