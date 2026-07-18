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

        await page.locator("#textInput").fill("captura la pantalla")
        await page.locator("#textForm button").click()
        gate = page.locator("#actionConfirmation")
        await gate.wait_for(state="visible", timeout=15_000)
        gate_text = await gate.inner_text()

        await page.locator("#rejectActionButton").click()
        await gate.wait_for(state="hidden", timeout=15_000)
        await page.get_by_text("Acción cancelada", exact=False).wait_for(
            state="visible", timeout=15_000
        )

        await page.locator("#textInput").fill("estado del sistema")
        await page.locator("#textForm button").click()
        await page.get_by_text("CPU", exact=False).last.wait_for(state="visible", timeout=15_000)
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
        }
    finally:
        await browser.close()


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
