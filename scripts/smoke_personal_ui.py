"""Read-only browser smoke test for the personal assistant control surfaces."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    errors: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto("http://127.0.0.1:8765", wait_until="networkidle")
        await page.locator("#controlDeckButton").click()
        await page.locator("#deckTabAssistant").click()
        await page.get_by_role("heading", name="Tu asistente cotidiano").wait_for()

        await page.get_by_role("button", name="Automatizaciones proactivas").click()
        await page.get_by_role("heading", name="Automatizaciones proactivas").wait_for()
        automation_rows = await page.locator(".automation-edit-row").count()

        await page.get_by_role("button", name="Ver y corregir memoria").click()
        await page.get_by_role("heading", name="Mapa personal estructurado").wait_for()
        await page.screenshot(path=Path(".data") / "smoke-personal-ui.png", full_page=True)
        await page.goto("http://127.0.0.1:8765/mail", wait_until="networkidle")
        await page.get_by_role("heading", name="Atención priorizada").wait_for()
        await page.wait_for_function(
            "() => document.querySelector('#insights')?.children.length > 0"
        )
        attention_items = await page.locator("#insights .attention-item").count()
        await page.goto("http://127.0.0.1:8765/organizer", wait_until="networkidle")
        await page.get_by_role("heading", name="Finanzas del mes").wait_for()
        await page.wait_for_function(
            "() => document.querySelector('#financeTotal')?.textContent !== '$—'"
        )
        finance_transactions = await page.locator(".finance-transaction").count()
        finance_total = await page.locator("#financeTotal").inner_text()
        finance_income = await page.locator("#financeIncome").inner_text()
        finance_history = await page.locator(".finance-history-item").count()
        await page.wait_for_function(
            "() => document.querySelector('#reliabilityChecks')?.children.length > 0"
        )
        reliability_checks = await page.locator("#reliabilityChecks article").count()
        await page.locator("#finances").screenshot(
            path=Path(".data") / "smoke-finance-ui.png"
        )
        mobile = await browser.new_page(
            viewport={"width": 412, "height": 915},
            device_scale_factor=2.6,
            is_mobile=True,
            has_touch=True,
        )
        mobile.on("pageerror", lambda error: errors.append(str(error)))
        await mobile.goto("http://127.0.0.1:8765/organizer", wait_until="networkidle")
        await mobile.wait_for_function(
            "() => document.querySelector('#financeTotal')?.textContent !== '$—'"
        )
        mobile_overflow = await mobile.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        await mobile.locator("#finances").screenshot(
            path=Path(".data") / "smoke-finance-mobile-ui.png"
        )
        await browser.close()

    result = {
        "automation_rules_visible": automation_rows,
        "structured_memory_visible": True,
        "mail_attention_visible": True,
        "mail_attention_items": attention_items,
        "finance_visible": True,
        "finance_transactions": finance_transactions,
        "finance_total": finance_total,
        "finance_income": finance_income,
        "finance_history_months": finance_history,
        "reliability_checks": reliability_checks,
        "finance_mobile_overflow": mobile_overflow,
        "browser_errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    if (
        automation_rows != 5
        or finance_transactions < 1
        or finance_history != 6
        or reliability_checks < 5
        or mobile_overflow
        or errors
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
