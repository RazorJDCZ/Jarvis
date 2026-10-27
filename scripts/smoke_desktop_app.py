"""Acceptance test for the installed Jarvis desktop shell without changing user data."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import httpx
import psutil
import win32gui
from PIL import ImageGrab
from pywinauto import Desktop

DESKTOP_EXE = Path.home() / "Desktop" / "Jarvis.exe"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def jarvis_desktop_processes() -> list[psutil.Process]:
    matches: list[psutil.Process] = []
    expected = DESKTOP_EXE.resolve()
    for process in psutil.process_iter(("pid", "exe")):
        try:
            executable = process.info.get("exe")
            if executable and Path(executable).resolve() == expected:
                matches.append(process)
        except (OSError, psutil.Error):
            continue
    return matches


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def health_ready() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:8765/api/health", timeout=2, trust_env=False)
        return response.status_code == 200 and response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def choose_close_option(control_id: int) -> None:
    dialog = Desktop(backend="win32").window(title="Cerrar Jarvis")
    dialog.wait("exists visible ready", timeout=8)
    dialog.child_window(control_id=control_id, class_name="Button").click()


def ambient_button_text(window) -> str:
    try:
        return next(
            (
                control.window_text()
                for control in window.descendants()
                if control.element_info.control_type == "Button"
                and "MODO AMBIENTAL" in control.window_text()
            ),
            "",
        )
    except Exception:  # The WebView DOM is briefly replaced by the native loader.
        return ""


def main() -> None:
    if not DESKTOP_EXE.is_file():
        raise SystemExit(f"No existe {DESKTOP_EXE}")

    window = Desktop(backend="uia").window(title="Jarvis")
    if not window.exists(timeout=2):
        subprocess.Popen([str(DESKTOP_EXE)])  # noqa: S603
    window.wait("exists visible ready", timeout=20)
    handle = window.handle
    web_loaded = any(
        control.window_text() == "JARVIS // Neural Interface"
        for control in window.descendants()
    )

    rectangle = window.rectangle()
    screenshot_path = PROJECT_ROOT / ".data" / "jarvis-desktop-app.png"
    ImageGrab.grab(
        bbox=(rectangle.left, rectangle.top, rectangle.right, rectangle.bottom),
        all_screens=True,
    ).save(screenshot_path)

    second = subprocess.Popen([str(DESKTOP_EXE)])  # noqa: S603
    second_instance_exited = wait_until(lambda: second.poll() is not None, timeout=8)
    one_instance = len(jarvis_desktop_processes()) == 1

    # Cancel must be a true no-op.
    win32gui.PostMessage(handle, 0x0010, 0, 0)  # WM_CLOSE
    choose_close_option(2)  # IDCANCEL
    cancel_keeps_interface = wait_until(
        lambda: win32gui.IsWindowVisible(handle) and len(jarvis_desktop_processes()) == 1,
        timeout=5,
    )

    ambient_button = next(
        (
            control
            for control in window.descendants()
            if control.element_info.control_type == "Button"
            and "MODO AMBIENTAL" in control.window_text()
        ),
        None,
    )
    ambient_started = False
    ambient_stopped_on_close = False
    if ambient_button is not None:
        ambient_button.click_input()
        ambient_started = wait_until(lambda: "Escuchando" in ambient_button_text(window), timeout=8)

    # "No" closes the WebView process but intentionally preserves the lightweight core.
    win32gui.PostMessage(handle, 0x0010, 0, 0)  # WM_CLOSE
    choose_close_option(7)  # IDNO
    background_closes_interface = wait_until(
        lambda: not jarvis_desktop_processes(), timeout=10
    )
    background_keeps_core = health_ready()

    subprocess.Popen([str(DESKTOP_EXE)])  # noqa: S603
    window = Desktop(backend="uia").window(title="Jarvis")
    window.wait("exists visible ready", timeout=20)
    handle = window.handle
    ambient_stopped_on_close = wait_until(
        lambda: "MODO AMBIENTAL" in ambient_button_text(window)
        and "Escuchando" not in ambient_button_text(window),
        timeout=10,
    )

    with httpx.Client(timeout=5, trust_env=False) as client:
        health = client.get("http://127.0.0.1:8765/api/health")
        health.raise_for_status()
        mail = client.get("http://127.0.0.1:8765/api/mail/status")
        mail.raise_for_status()
        organizer = client.get("http://127.0.0.1:8765/api/organizer/today")
        organizer.raise_for_status()

    mail_payload = mail.json()
    organizer_payload = organizer.json()
    mail_account_count = len(mail_payload.get("accounts", []))
    calendar = organizer_payload.get("calendar", {})

    # "Sí" stops the core and supervisor. Reopening the EXE must restore everything.
    win32gui.PostMessage(handle, 0x0010, 0, 0)  # WM_CLOSE
    choose_close_option(6)  # IDYES
    complete_close_stops_interface = wait_until(
        lambda: not jarvis_desktop_processes(), timeout=45
    )
    complete_close_stops_core = wait_until(lambda: not health_ready(), timeout=10)

    subprocess.Popen([str(DESKTOP_EXE)])  # noqa: S603
    core_restarts = wait_until(health_ready, timeout=190)
    restored = Desktop(backend="uia").window(title="Jarvis")
    interface_restarts = restored.exists(timeout=20)
    result = {
        "web_interface_loaded": web_loaded,
        "single_instance": second_instance_exited and one_instance,
        "cancel_keeps_interface": cancel_keeps_interface,
        "background_closes_interface": background_closes_interface,
        "background_keeps_core": background_keeps_core,
        "complete_close_stops_interface": complete_close_stops_interface,
        "complete_close_stops_core": complete_close_stops_core,
        "core_restarts": core_restarts,
        "interface_restarts": interface_restarts,
        "ambient_starts": ambient_started,
        "ambient_stops_when_window_closes": ambient_stopped_on_close,
        "jarvis_health": health.json().get("status") == "ok",
        "mail_accounts_preserved": mail_account_count > 0,
        "mail_account_count": mail_account_count,
        "calendar_connected": bool(calendar.get("configured") and calendar.get("accounts")),
        "screenshot": str(screenshot_path),
    }
    print(json.dumps(result, ensure_ascii=False))
    required = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "mail_account_count",
            "screenshot",
        }
    }
    if not all(required.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
