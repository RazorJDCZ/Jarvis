from __future__ import annotations

import json
import time

from jarvis.actions.windows import AppController, AudioController, WindowController


def verify() -> dict[str, object]:
    windows = WindowController()
    apps = AppController(windows)
    audio = AudioController()

    calculator = apps.open("calculator")
    calculator_visible = windows.find(aliases=("Calculadora", "Calculator")) is not None
    calculator_title = "Calculadora" if windows.find("Calculadora") else "Calculator"
    calculator_closed = windows.close(calculator_title)

    notepad = apps.open("notepad")
    typed = windows.type_text("JARVIS_WINDOWS_SMOKE") if notepad.success else None
    controls = windows.inspect_controls() if notepad.success else None
    cleared = windows.send_hotkey("select_all") if notepad.success else None
    if cleared is not None and cleared.success:
        cleared = windows.press_key("backspace")
    notepad_closed = windows.close("Bloc de notas" if windows.find("Bloc de notas") else "Notepad")

    initial_volume = audio.get_level()
    changed = None
    restored = None
    if initial_volume.success:
        original = int(initial_volume.details["level"])
        temporary = original - 1 if original > 0 else original + 1
        changed = audio.set_level(temporary)
        restored = audio.set_level(original)

    time.sleep(0.4)
    return {
        "calculator_opened": calculator.success and calculator_visible,
        "calculator_closed": calculator_closed.success,
        "notepad_opened": notepad.success and notepad.details.get("verified") is True,
        "notepad_typed": typed is not None and typed.success,
        "notepad_controls": bool(
            controls and controls.success and controls.details.get("controls")
        ),
        "notepad_cleared": cleared is not None and cleared.success,
        "notepad_closed": notepad_closed.success,
        "volume_read": initial_volume.success,
        "volume_message": initial_volume.message,
        "volume_changed": changed is not None and changed.success,
        "volume_change_message": changed.message if changed is not None else None,
        "volume_restored": restored is not None
        and restored.success
        and restored.details.get("level") == initial_volume.details.get("level"),
        "volume_restore_message": restored.message if restored is not None else None,
    }


def main() -> None:
    print(json.dumps(verify(), ensure_ascii=False))


if __name__ == "__main__":
    main()
