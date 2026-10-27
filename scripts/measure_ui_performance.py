from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

METRIC_NAMES = {
    "TaskDuration",
    "ScriptDuration",
    "LayoutDuration",
    "RecalcStyleDuration",
    "JSHeapUsedSize",
    "Nodes",
}


def select_metrics(payload: dict[str, object]) -> dict[str, float]:
    metrics = payload.get("metrics", [])
    return {
        item["name"]: item["value"]
        for item in metrics
        if isinstance(item, dict) and item.get("name") in METRIC_NAMES
    }


async def measure() -> dict[str, float | int]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        await page.goto("http://127.0.0.1:8765", wait_until="domcontentloaded")
        await page.locator("#micButton").wait_for(state="visible")
        await page.wait_for_timeout(1_500)
        session = await page.context.new_cdp_session(page)
        await session.send("Performance.enable")
        before = select_metrics(await session.send("Performance.getMetrics"))
        await page.wait_for_timeout(5_000)
        after = select_metrics(await session.send("Performance.getMetrics"))
        await browser.close()

    result: dict[str, float | int] = {
        name: round(after.get(name, 0) - before.get(name, 0), 4)
        for name in METRIC_NAMES
        if name not in {"JSHeapUsedSize", "Nodes"}
    }
    result["JSHeapUsedMB"] = round(after.get("JSHeapUsedSize", 0) / 1_048_576, 2)
    result["Nodes"] = int(after.get("Nodes", 0))
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(measure()), sort_keys=True))
