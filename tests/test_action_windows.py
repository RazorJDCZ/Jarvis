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


class FakeAppItem:
    def __init__(self, name: str, app_id: str, target: str = "") -> None:
        self.Name = name
        self.Path = app_id
        self.target = target
        self.invoked = False

    def ExtendedProperty(self, _name: str) -> str:
        return self.target

    def InvokeVerb(self) -> None:
        self.invoked = True


class FakeAppItems:
    def __init__(self, items: list[FakeAppItem]) -> None:
        self._items = items
        self.Count = len(items)

    def Item(self, index: int) -> FakeAppItem:
        return self._items[index]


class FakeAppsFolder:
    def __init__(self, items: list[FakeAppItem]) -> None:
        self.items = FakeAppItems(items)

    def Items(self) -> FakeAppItems:
        return self.items


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


def test_windows_dialog_detection_uses_accessible_dialog_and_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Info:
        def __init__(self, control_type: str, automation_id: str = "") -> None:
            self.control_type = control_type
            self.automation_id = automation_id

    class Control:
        def __init__(
            self,
            name: str,
            control_type: str,
            handle: int,
            class_name: str = "",
            automation_id: str = "",
            children: list[object] | None = None,
            descendants: list[object] | None = None,
        ) -> None:
            self._name = name
            self._class_name = class_name
            self.handle = handle
            self.element_info = Info(control_type, automation_id)
            self._children = children or []
            self._descendants = descendants or []

        def window_text(self) -> str:
            return self._name

        def class_name(self) -> str:
            return self._class_name

        def children(self) -> list[object]:
            return self._children

        def descendants(self) -> list[object]:
            return self._descendants

        @staticmethod
        def is_visible() -> bool:
            return True

        @staticmethod
        def is_enabled() -> bool:
            return True

    message = Control(
        "¿Quieres guardar los cambios?",
        "Text",
        3,
        automation_id="MainInstruction",
    )
    save = Control("Guardar", "Button", 4, automation_id="CommandButton_6")
    discard = Control("No guardar", "Button", 5, automation_id="CommandButton_7")
    dialog = Control(
        "Bloc de notas",
        "Window",
        2,
        class_name="#32770",
        descendants=[message, save, discard],
    )
    parent = Control(
        "*Sin título: Bloc de notas",
        "Window",
        1,
        class_name="Notepad",
        children=[dialog],
    )
    controller = WindowController()
    controls = {1: parent, 2: dialog}
    desktop = type("Desktop", (), {"window": lambda _self, handle: controls[handle]})()
    monkeypatch.setattr(controller, "_desktop", lambda: desktop)
    monkeypatch.setattr(controller, "_native_dialog_handles", lambda: ((1, 2),))

    detected = controller.dialogs()

    assert len(detected) == 1
    assert detected[0].parent_handle == 1
    assert detected[0].dialog_handle == 2
    assert detected[0].message == "¿Quieres guardar los cambios?"
    assert detected[0].options == ("Guardar", "No guardar")


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


def test_window_lookup_scores_native_titles_without_querying_every_uia_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowController()
    monkeypatch.setattr(
        controller,
        "_native_visible_windows",
        lambda: [(10, "Calculadora"), (20, "Calculadora - ayuda"), (30, "Otro")],
    )
    desktop = type("Desktop", (), {"window": lambda _self, handle: f"window-{handle}"})()
    monkeypatch.setattr(controller, "_desktop", lambda: desktop)

    found = controller.find(aliases=("Calculadora", "Calculator"))
    listed = controller.list_windows()

    assert found == "window-10"
    assert listed.details["windows"] == ["Calculadora", "Calculadora - ayuda", "Otro"]


def test_win32_handles_are_canonicalized_when_callbacks_sign_extend_them() -> None:
    assert WindowController._canonical_window_handle(0xFFFFFFFFAE1F187C) == 0xAE1F187C


def test_close_handle_revalidates_exact_window_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowController()
    monkeypatch.setattr(
        controller,
        "visible_window_snapshot",
        lambda: {41: "Documento privado"},
    )

    result = controller.close_handle(41, "Otro documento")

    assert result.success is False
    assert result.details["identity_changed"] is True


def test_close_handle_only_posts_to_revalidated_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowController()
    snapshots = iter(({41: "Prueba"}, {}))
    monkeypatch.setattr(controller, "visible_window_snapshot", lambda: next(snapshots))
    posted: list[tuple[int, int, int, int]] = []
    api = type(
        "Api",
        (),
        {"PostMessageW": lambda _self, *args: posted.append(args) or True},
    )()
    monkeypatch.setattr(controller, "_window_api", lambda: api)

    result = controller.close_handle(41, "Prueba")

    assert result.success is True
    assert result.details["verified"] is True
    assert posted == [(41, 0x0010, 0, 0)]


def test_close_handle_uses_exact_accessible_fallback_when_post_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowController()
    fallback: list[tuple[int, str]] = []
    monkeypatch.setattr(
        controller,
        "visible_window_snapshot",
        lambda: {} if fallback else {52: "FAX Utility"},
    )
    api = type("Api", (), {"PostMessageW": lambda *_args: False})()
    monkeypatch.setattr(controller, "_window_api", lambda: api)
    monkeypatch.setattr(
        controller,
        "_invoke_accessible_titlebar_close",
        lambda handle, title: fallback.append((handle, title)) or True,
    )

    result = controller.close_handle(52, "FAX Utility")

    assert result.success is True
    assert result.details["accessible_fallback"] is True
    assert fallback == [(52, "FAX Utility")]


def test_close_handle_uses_safe_system_exit_for_magnifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = WindowController()
    special: list[tuple[int, str]] = []
    monkeypatch.setattr(
        controller,
        "visible_window_snapshot",
        lambda: {} if special else {63: "Lupa"},
    )
    api = type("Api", (), {"PostMessageW": lambda *_args: False})()
    monkeypatch.setattr(controller, "_window_api", lambda: api)
    monkeypatch.setattr(
        controller,
        "_close_special_system_window",
        lambda handle, title: special.append((handle, title)) or True,
    )

    result = controller.close_handle(63, "Lupa")

    assert result.success is True
    assert result.details["special_system_exit"] is True
    assert special == [(63, "Lupa")]


def test_installed_application_inventory_is_cached_for_repeated_language_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = FakeAppItem("Discord", "Discord.App", r"C:\Apps\Discord\Update.exe")
    folder = FakeAppsFolder([item])
    calls = {"count": 0}

    def apps_folder() -> FakeAppsFolder:
        calls["count"] += 1
        return folder

    controller = AppController(WindowController())
    monkeypatch.setattr(controller, "_apps_folder", apps_folder)

    assert controller.find_installed_apps("discord")
    assert controller.find_installed_apps("disc")
    assert controller.installed_apps()
    assert calls["count"] == 1


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


def test_static_app_uses_audited_shell_execute_when_elevation_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = WindowController()
    monkeypatch.setattr(windows, "find", lambda **_kwargs: None)

    def elevation_required(*_args: object, **_kwargs: object) -> None:
        error = OSError(740, "requires elevation")
        error.winerror = 740  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr("jarvis.actions.windows.subprocess.Popen", elevation_required)
    launched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "jarvis.actions.windows.os.startfile",
        lambda executable, *, arguments: launched.append((executable, arguments)),
    )
    monkeypatch.setattr("jarvis.actions.windows.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(AppController, "_wait_for_window", lambda *_args: object())
    monkeypatch.setattr(
        windows,
        "focus",
        lambda **_kwargs: ExecutionResult(True, "focused"),
    )

    result = AppController(windows).open("task_manager")

    assert result.success is True
    assert result.details["verified"] is True
    assert launched == [("taskmgr.exe", "")]


def test_windows_apps_inventory_includes_apps_and_filters_execution_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        FakeAppItem("Discord", "Discord.App", r"C:\Apps\Discord\Update.exe"),
        FakeAppItem("Calculadora", "Calculator.App!Main"),
        FakeAppItem("Brawlhalla", "steam://rungameid/291550", "steam://rungameid/291550"),
        FakeAppItem("Git Bash", "Git.Bash", r"C:\Program Files\Git\git-bash.exe"),
        FakeAppItem("Python 3.13", "Python", r"C:\Python313\python.exe"),
        FakeAppItem("Manual", "Manual", r"C:\Apps\manual.html"),
        FakeAppItem("Uninstall Example", "Uninstall", r"C:\Apps\uninstall.exe"),
        FakeAppItem("Actualización de la app", "Updater", r"C:\Apps\updater.exe"),
        FakeAppItem("Configuración del sistema", "MSConfig", r"C:\Windows\msconfig.exe"),
        FakeAppItem("Ajustes EPSON Scan", "Epson.Settings", r"C:\Apps\escfg.exe"),
        FakeAppItem("Asistencia rápida", "QuickAssist", r"C:\Windows\quickassist.exe"),
        FakeAppItem("Comprobación de estado de la PC", "Health", r"C:\Apps\health.exe"),
        FakeAppItem("Grabación de acciones de usuario", "PSR", r"C:\Windows\psr.exe"),
        FakeAppItem("MSI Afterburner", "Afterburner", r"C:\Apps\MSIAfterburner.exe"),
        FakeAppItem("Monitor de recursos", "Resmon", r"C:\Windows\resmon.exe"),
        FakeAppItem("Roblox Studio", "Roblox", r"C:\Apps\RobloxStudioInstaller.exe"),
        FakeAppItem("Ejecutar", "Windows.Run"),
    ]
    controller = AppController(WindowController())
    monkeypatch.setattr(controller, "_apps_folder", lambda: FakeAppsFolder(items))

    apps = controller.installed_apps()

    assert [app.name for app in apps] == ["Brawlhalla", "Calculadora", "Discord"]
    assert controller.find_installed_apps("discord")[0].app_id == "Discord.App"
    assert controller.find_installed_apps("python") == ()


def test_installed_app_is_revalidated_and_launched_through_windows_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = FakeAppItem("Discord", "Discord.App", r"C:\Apps\Discord\Update.exe")
    windows = WindowController()
    monkeypatch.setattr(
        windows,
        "focus",
        lambda **_kwargs: ExecutionResult(True, "focused"),
    )
    controller = AppController(windows)
    monkeypatch.setattr(controller, "_apps_folder", lambda: FakeAppsFolder([item]))
    monkeypatch.setattr("jarvis.actions.windows.time.sleep", lambda _seconds: None)
    calls: list[list[str]] = []

    class FakeProcess:
        pid = 54

    monkeypatch.setattr(
        "jarvis.actions.windows.subprocess.Popen",
        lambda command, **_kwargs: calls.append(command) or FakeProcess(),
    )

    result = controller.open(
        "discord",
        app_id="Discord.App",
        display_name="Discord",
        target_path=r"C:\Apps\Discord\Update.exe",
    )

    assert result.success is True
    assert result.details["source"] == "windows-apps-folder"
    assert result.details["launcher_pid"] == 54
    assert calls == [["explorer.exe", r"shell:AppsFolder\Discord.App"]]
    assert item.invoked is False


def test_installed_app_launch_rejects_changed_catalog_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = FakeAppItem("Discord", "Discord.App", r"C:\Changed\Discord.exe")
    controller = AppController(WindowController())
    monkeypatch.setattr(controller, "_apps_folder", lambda: FakeAppsFolder([item]))

    result = controller.open(
        "discord",
        app_id="Discord.App",
        display_name="Discord",
        target_path=r"C:\Expected\Discord.exe",
    )

    assert result.success is False
    assert item.invoked is False


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
