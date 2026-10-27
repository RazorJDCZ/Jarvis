"""Read-only visual smoke test for the Android-specific Jarvis surface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    errors: list[str] = []
    data_dir = Path(".data")
    data_dir.mkdir(exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(
            viewport={"width": 412, "height": 780},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 "
                "Chrome/140 Mobile Safari/537.36 JarvisAndroid/1.3.1"
            ),
        )
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        await page.locator(".orb-control").wait_for()

        actual_user_agent = await page.evaluate("navigator.userAgent")
        native_class = await page.locator("html.native-android").count()
        topbar_display = await page.locator(".topbar").evaluate(
            "node => getComputedStyle(node).display"
        )
        footer_display = await page.locator(".footer-bar").evaluate(
            "node => getComputedStyle(node).display"
        )
        orb_box = await page.locator(".orb-control").bounding_box()
        stage_box = await page.locator(".core-stage").bounding_box()

        await page.evaluate("document.body.classList.add('mobile-chat-hidden')")
        await page.wait_for_timeout(500)
        hidden_style = await page.locator(".conversation-panel").evaluate(
            "node => ({ visibility: getComputedStyle(node).visibility, "
            "opacity: getComputedStyle(node).opacity, "
            "transform: getComputedStyle(node).transform })"
        )
        await page.screenshot(path=data_dir / "android-shell-home.png", full_page=False)

        await page.evaluate("document.body.classList.remove('mobile-chat-hidden')")
        await page.wait_for_timeout(300)
        visible_position = await page.locator(".conversation-panel").evaluate(
            "node => getComputedStyle(node).position"
        )
        await page.screenshot(path=data_dir / "android-shell-chat.png", full_page=False)

        await page.evaluate(
            "document.getElementById('controlDeckCompactButton').click()"
        )
        deck_open = await page.locator("#controlDeckDialog").evaluate("node => node.open")
        await browser.close()

    result = {
        "user_agent": actual_user_agent,
        "native_class": native_class == 1,
        "desktop_header_hidden": topbar_display == "none",
        "desktop_footer_hidden": footer_display == "none",
        "chat_can_hide": (
            hidden_style["visibility"] == "hidden"
            or float(hidden_style["opacity"]) < 0.02
        ),
        "hidden_chat_style": hidden_style,
        "chat_is_bottom_sheet": visible_position == "fixed",
        "control_deck_opens": deck_open,
        "orb_fits_viewport": bool(
            orb_box
            and orb_box["x"] >= 0
            and orb_box["x"] + orb_box["width"] <= 412
        ),
        "stage_fills_viewport": bool(stage_box and stage_box["height"] >= 780),
        "browser_errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    if not all(
        value
        for key, value in result.items()
        if key not in {"browser_errors", "user_agent", "hidden_chat_style"}
    ) or errors:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
