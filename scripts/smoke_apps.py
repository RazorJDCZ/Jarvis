from __future__ import annotations

import json
import time

from jarvis.actions.windows import AppController, WindowController


def verify() -> dict[str, object]:
    windows = WindowController()
    apps = AppController(windows)
    inventory = apps.installed_apps()
    calculator = apps.find_installed_apps("calculadora")
    already_open = windows.find(aliases=("Calculadora", "Calculator")) is not None
    opened = None
    closed = None
    if calculator and not already_open:
        selected = calculator[0]
        opened = apps.open(
            "calculadora",
            app_id=selected.app_id,
            display_name=selected.name,
            target_path=selected.target_path,
        )
        time.sleep(0.4)
        closed = windows.close("Calculadora" if windows.find("Calculadora") else "Calculator")
    return {
        "safe_inventory_count": len(inventory),
        "common_apps_found": all(
            apps.find_installed_apps(name)
            for name in ("calculadora", "discord", "visual studio code", "spotify", "word")
        ),
        "execution_surfaces_blocked": not any(
            blocked in app.name.casefold()
            for app in inventory
            for blocked in ("powershell", "símbolo del sistema", "terminal", "ejecutar")
        ),
        "dynamic_calculator_opened": already_open or bool(opened and opened.success),
        "dynamic_calculator_verified": already_open
        or bool(opened and opened.details.get("verified") is True),
        "dynamic_calculator_closed": already_open or bool(closed and closed.success),
        "preexisting_calculator_left_untouched": already_open,
    }


def main() -> None:
    print(json.dumps(verify(), ensure_ascii=False))


if __name__ == "__main__":
    main()
