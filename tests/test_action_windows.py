from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.actions.models import ExecutionResult
from jarvis.actions.windows import (
    AppController,
    AudioController,
    ClipboardController,
    DesktopInputController,
    PathController,
    WindowController,
)


class FakeEndpoint:
    def __init__(self, level: float = 0.5, muted: bool = False) -> None:
        self.level = level
        self.muted = muted

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.level

    def SetMasterVolumeLevelScalar(self, value: float, _context: object) -> None:
        self.level = value

    def GetMute(self) -> int:
        return int(self.muted)

    def SetMute(self, value: int, _context: object) -> None:
        self.muted = bool(value)


class FakeComtypes:
    def __init__(self) -> None:
        self.uninitialized = False

    def CoUninitialize(self) -> None:
        self.uninitialized = True


def test_audio_level_is_set_and_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = FakeEndpoint()
    comtypes = FakeComtypes()
    controller = AudioController()
    monkeypatch.setattr(controller, "_endpoint", lambda: (endpoint, comtypes))

    result = controller.set_level(37)

    assert result.success is True
    assert result.details["level"] == 37
    assert comtypes.uninitialized is True


def test_relative_audio_change_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = FakeEndpoint(0.96)
    controller = AudioController()
    monkeypatch.setattr(controller, "_endpoint", lambda: (endpoint, FakeComtypes()))

    result = controller.change_level(10)

    assert result.details == {"previous": 96, "level": 100, "verified": True}


def test_audio_mute_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = FakeEndpoint()
    controller = AudioController()
    monkeypatch.setattr(controller, "_endpoint", lambda: (endpoint, FakeComtypes()))

    result = controller.mute(True)

    assert result.success is True
    assert result.details["muted"] is True


def test_audio_level_can_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = FakeEndpoint(0.63, muted=True)
    controller = AudioController()
    monkeypatch.setattr(controller, "_endpoint", lambda: (endpoint, FakeComtypes()))

    result = controller.get_level()

    assert result.success is True
    assert result.details == {"level": 63, "muted": True, "verified": True}


def test_audio_reuses_existing_com_apartment(monkeypatch: pytest.MonkeyPatch) -> None:
    import comtypes
    from pycaw.pycaw import AudioUtilities

    endpoint = FakeEndpoint()
    speakers = type("Speakers", (), {"EndpointVolume": endpoint})()

    def changed_mode() -> None:
        raise OSError(AudioController._RPC_E_CHANGED_MODE, "COM apartment already selected")

    monkeypatch.setattr(comtypes, "CoInitialize", changed_mode)
    monkeypatch.setattr(AudioUtilities, "GetSpeakers", lambda: speakers)

    resolved, cleanup = AudioController._endpoint()

    assert resolved is endpoint
    assert cleanup is None


def test_media_key_sends_down_and_up(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[int, int, int, int]] = []

    class FakeUser32:
        def keybd_event(self, *args: int) -> None:
            events.append(args)

    monkeypatch.setattr(
        "jarvis.actions.windows.ctypes.WinDLL",
        lambda *_args, **_kwargs: FakeUser32(),
    )

    result = AudioController().media_key("play_pause")

    assert result.success is True
    assert events == [(0xB3, 0, 0, 0), (0xB3, 0, 0x0002, 0)]


def test_visual_click_is_cancelled_if_cursor_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = DesktopInputController()
    clicked: list[tuple[int, int]] = []
    monkeypatch.setattr(controller, "_cursor_position", lambda: (300, 400))
    monkeypatch.setattr(
        controller,
        "click",
        lambda x, y: clicked.append((x, y)) or ExecutionResult(True, "clicked"),
    )

    result = controller.click_if_cursor_unchanged(100, 200)

    assert result.success is False
    assert result.details["cursor_moved_by_user"] is True
    assert clicked == []


def test_visual_click_runs_if_cursor_stayed_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = DesktopInputController()
    monkeypatch.setattr(controller, "_cursor_position", lambda: (103, 198))
    monkeypatch.setattr(
        controller,
        "click",
        lambda x, y: ExecutionResult(True, "clicked", {"point": [x, y]}),
    )

    result = controller.click_if_cursor_unchanged(100, 200)

    assert result.success is True
    assert result.details["point"] == [100, 200]


def test_static_app_focuses_existing_window(monkeypatch: pytest.MonkeyPatch) -> None:
    windows = WindowController()
    existing = object()
    monkeypatch.setattr(windows, "find", lambda **_kwargs: existing)
    monkeypatch.setattr(
        windows,
        "focus",
        lambda **_kwargs: type("Result", (), {"success": True})(),
    )

    result = AppController(windows).open("calculator")

    assert result.success is True
    assert result.details == {"verified": True, "already_open": True}


def test_static_app_uses_fixed_command_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    windows = WindowController()
    monkeypatch.setattr(windows, "find", lambda **_kwargs: None)
    calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        pid = 42

        @staticmethod
        def poll() -> None:
            return None

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr("jarvis.actions.windows.subprocess.Popen", fake_popen)
    monkeypatch.setattr("jarvis.actions.windows.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(AppController, "_wait_for_window", lambda *_args: None)

    result = AppController(windows).open("notepad")

    assert result.success is True
    assert calls[0][0] == ["notepad.exe"]
    assert "shell" not in calls[0][1]


@pytest.mark.parametrize(
    ("target", "trusted"),
    [
        (r"C:\Program Files\Spotify\Spotify.exe", True),
        (r"C:\Windows\System32\cmd.exe", False),
        (r"C:\Program Files\PowerShell\pwsh.exe", False),
    ],
)
def test_start_menu_shortcut_target_is_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    trusted: bool,
) -> None:
    shortcut = tmp_path / "App.lnk"
    shortcut.write_bytes(b"shortcut")

    class FakeShortcut:
        TargetPath = target

    class FakeShell:
        @staticmethod
        def CreateShortcut(_path: str) -> FakeShortcut:
            return FakeShortcut()

    monkeypatch.setattr("win32com.client.Dispatch", lambda _name: FakeShell())
    controller = AppController(WindowController())
    controller._start_menu_roots = (tmp_path,)

    assert controller._trusted_shortcut(shortcut) is trusted


def test_clipboard_round_trip_uses_text_api(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"text": "original"}
    monkeypatch.setattr("pyperclip.copy", lambda value: state.update(text=value))
    monkeypatch.setattr("pyperclip.paste", lambda: state["text"])
    controller = ClipboardController()

    written = controller.write("Jarvis seguro")
    read = controller.read()

    assert written.success is True
    assert read.details["text"] == "Jarvis seguro"


def test_safe_file_type_opens_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "reporte.pdf"
    document.write_bytes(b"pdf")
    opened: list[Path] = []
    monkeypatch.setattr("jarvis.actions.windows.os.startfile", opened.append)

    result = PathController().open_file(str(document))

    assert result.success is True
    assert opened == [document.resolve()]


@pytest.mark.parametrize(
    "filename",
    ["payload.exe", "script.ps1", "macro.docm", "site.url", "program.py", "page.html"],
)
def test_files_outside_safe_extension_allowlist_are_blocked(
    tmp_path: Path,
    filename: str,
) -> None:
    path = tmp_path / filename
    path.write_text("test", encoding="utf-8")

    result = PathController().open_file(str(path))

    assert result.success is False
    assert "lista segura" in result.message
