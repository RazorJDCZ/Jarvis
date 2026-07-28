from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.actions.browser import ControlledBrowser


class FakeLocator:
    def __init__(
        self,
        count: int = 1,
        text: str = "Contenido visible",
        href: str | None = None,
    ) -> None:
        self._count = count
        self._text = text
        self.first = self
        self.clicked = False
        self.filled: str | None = None
        self.href = href

    async def count(self) -> int:
        return self._count

    async def click(self, **_kwargs: object) -> None:
        self.clicked = True

    async def fill(self, text: str, **_kwargs: object) -> None:
        self.filled = text

    async def inner_text(self, **_kwargs: object) -> str:
        return self._text

    def nth(self, _index: int) -> FakeLocator:
        return self

    async def get_attribute(self, name: str) -> str | None:
        return self.href if name == "href" else None


class FakePage:
    def __init__(self, title: str = "Página de prueba") -> None:
        self.url = "about:blank"
        self.page_title = title
        self.closed = False
        self.last_locator: FakeLocator | None = None
        self.role_locators: list[FakeLocator] = []
        self.label_locators: list[FakeLocator] = []
        self.navigation: list[str] = []
        self.result_locator = FakeLocator(
            text="Resultado seguro",
            href="https://result.example/demo",
        )

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    async def bring_to_front(self) -> None:
        return None

    async def title(self) -> str:
        return self.page_title

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True

    async def go_back(self, **_kwargs: object) -> None:
        self.navigation.append("back")

    async def go_forward(self, **_kwargs: object) -> None:
        self.navigation.append("forward")

    async def reload(self, **_kwargs: object) -> None:
        self.navigation.append("refresh")

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def locator(self, _selector: str) -> FakeLocator:
        if _selector == "a:has(h3)":
            return self.result_locator
        return FakeLocator(text="Texto   principal de la página")

    def get_by_role(self, _role: str, **_kwargs: object) -> FakeLocator:
        self.last_locator = FakeLocator()
        self.role_locators.append(self.last_locator)
        return self.last_locator

    def get_by_text(self, _text: str, **_kwargs: object) -> FakeLocator:
        return FakeLocator(count=0)

    def get_by_label(self, _field: str, **_kwargs: object) -> FakeLocator:
        self.last_locator = FakeLocator()
        self.label_locators.append(self.last_locator)
        return self.last_locator

    def get_by_placeholder(self, _field: str, **_kwargs: object) -> FakeLocator:
        return FakeLocator(count=0)


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    async def new_page(self) -> FakePage:
        page = FakePage("Nueva pestaña")
        self.pages.append(page)
        return page


def controller(
    tmp_path: Path, page: FakePage, monkeypatch: pytest.MonkeyPatch
) -> ControlledBrowser:
    browser = ControlledBrowser(tmp_path, "https://search.example/?q={query}")
    browser._page = page
    browser._active_browser = "edge"

    async def page_factory(_browser: str | None = None) -> FakePage:
        return browser._page

    monkeypatch.setattr(browser, "_ensure_page", page_factory)
    return browser


def test_browser_selection_supports_installed_default_and_explicit_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ControlledBrowser,
        "installed_browsers",
        classmethod(lambda _cls: ("chrome", "edge")),
    )
    monkeypatch.setattr(ControlledBrowser, "_windows_default_browser", lambda: "chrome")

    assert ControlledBrowser.normalize_browser(None) == "chrome"
    assert ControlledBrowser.normalize_browser("Google Chrome") == "chrome"
    assert ControlledBrowser.normalize_browser("Microsoft Edge") == "edge"


def test_browser_selection_rejects_unknown_or_missing_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ControlledBrowser,
        "installed_browsers",
        classmethod(lambda _cls: ("edge",)),
    )

    with pytest.raises(ValueError, match="compatible"):
        ControlledBrowser.normalize_browser("Firefox")
    with pytest.raises(RuntimeError, match="no está instalado"):
        ControlledBrowser.normalize_browser("Chrome")


def test_browser_launch_uses_normal_persistent_profile(tmp_path: Path) -> None:
    executable = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    profile = tmp_path / "browser-profile-chrome"

    arguments = ControlledBrowser._launch_arguments(executable, 12345, profile)

    assert "--new-window" in arguments
    assert f"--user-data-dir={profile}" in arguments
    assert "--incognito" not in arguments
    assert "--inprivate" not in arguments
    assert "--guest" not in arguments


def test_personal_launch_reuses_regular_browser_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    monkeypatch.setattr(
        ControlledBrowser,
        "_personal_profile_directory",
        classmethod(lambda _cls, _browser: "Profile 3"),
    )

    arguments = ControlledBrowser._personal_launch_arguments(
        executable,
        "chrome",
        "https://www.google.com/search?q=jarvis",
    )

    assert "--profile-directory=Profile 3" in arguments
    assert "--new-window" in arguments
    assert not any(argument.startswith("--user-data-dir") for argument in arguments)
    assert not any("remote-debugging" in argument for argument in arguments)
    assert "--incognito" not in arguments


@pytest.mark.asyncio
async def test_personal_mode_opens_url_without_owning_or_closing_user_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWindows:
        shortcuts: list[str] = []

        @staticmethod
        def focus(**_kwargs: object):
            from jarvis.actions.models import ExecutionResult

            return ExecutionResult(True, "focused")

        def send_browser_shortcut(self, shortcut: str):
            from jarvis.actions.models import ExecutionResult

            self.shortcuts.append(shortcut)
            return ExecutionResult(True, "sent")

    class FakeProcess:
        terminated = False

        @staticmethod
        def poll() -> None:
            return None

    launched: list[list[str]] = []

    def fake_popen(arguments: list[str], **_kwargs: object) -> FakeProcess:
        launched.append(arguments)
        return FakeProcess()

    monkeypatch.setattr(
        ControlledBrowser,
        "_browser_path",
        classmethod(lambda _cls, _browser: Path("chrome.exe")),
    )
    monkeypatch.setattr(
        ControlledBrowser,
        "installed_browsers",
        classmethod(lambda _cls: ("chrome",)),
    )
    monkeypatch.setattr(ControlledBrowser, "_windows_default_browser", lambda: "chrome")
    monkeypatch.setattr(
        ControlledBrowser,
        "_personal_profile_directory",
        classmethod(lambda *_: "Default"),
    )
    monkeypatch.setattr("jarvis.actions.browser.subprocess.Popen", fake_popen)
    monkeypatch.setattr("jarvis.actions.browser.time.sleep", lambda _seconds: None)
    windows = FakeWindows()
    browser = ControlledBrowser(
        tmp_path,
        "https://search.example/?q={query}",
        personal_profile=True,
        windows=windows,
    )

    opened = await browser.open("https://example.com")
    navigated = await browser.navigate("back")
    await browser.close()

    assert opened.success is True
    assert opened.details["profile_mode"] == "personal"
    assert launched[0][-1] == "https://example.com"
    assert windows.shortcuts == ["back"]
    assert navigated.success is True
    assert browser._process is None


def test_browser_process_gets_graceful_shutdown_before_termination(tmp_path: Path) -> None:
    browser = ControlledBrowser(tmp_path, "https://example.com/?q={query}")

    class FakeProcess:
        waited: list[float] = []
        terminated = False

        @staticmethod
        def poll() -> None:
            return None

        def wait(self, timeout: float) -> int:
            self.waited.append(timeout)
            return 0

        def terminate(self) -> None:
            self.terminated = True

    process = FakeProcess()
    browser._process = process

    browser._terminate_process(graceful_timeout=3.0)

    assert process.waited == [3.0]
    assert process.terminated is False
    assert browser._process is None


@pytest.mark.asyncio
async def test_open_and_search_report_verified_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage()
    browser = controller(tmp_path, page, monkeypatch)

    opened = await browser.open("https://example.com")
    searched = await browser.search("voz local")

    assert opened.success is True
    assert opened.details["verified"] is True
    assert opened.details["browser"] == "edge"
    assert searched.success is True
    assert page.url == "https://search.example/?q=voz+local"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["file:///C:/secrets.txt", "javascript:alert(1)", "https://u:p@example.com"],
)
async def test_open_rejects_unsafe_url_even_without_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    page = FakePage()
    browser = controller(tmp_path, page, monkeypatch)

    result = await browser.open(url)

    assert result.success is False
    assert page.url == "about:blank"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "template",
    [
        "javascript:alert({query})",
        "file:///C:/secrets?q={query}",
        "https://user:secret@example.com/?q={query}",
        "https://example.com/?q={query}&extra={unknown}",
        "https://example.com/search",
    ],
)
async def test_search_rejects_unsafe_or_invalid_provider_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
) -> None:
    page = FakePage()
    browser = controller(tmp_path, page, monkeypatch)
    browser.search_url = template

    result = await browser.search("prueba")

    assert result.success is False
    assert page.url == "about:blank"


@pytest.mark.asyncio
async def test_navigation_and_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage()
    browser = controller(tmp_path, page, monkeypatch)

    await browser.navigate("back")
    await browser.navigate("forward")
    await browser.navigate("refresh")
    read = await browser.read()

    assert page.navigation == ["back", "forward", "refresh"]
    assert read.success is True
    assert "Texto principal" in read.message


@pytest.mark.asyncio
async def test_click_and_fill_use_accessible_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage()
    browser = controller(tmp_path, page, monkeypatch)

    clicked = await browser.click("Aceptar")
    click_locator = page.role_locators[0]
    filled = await browser.fill("Nombre", "Juandi")
    fill_locator = page.label_locators[0]

    assert clicked.success is True
    assert click_locator.clicked is True
    assert filled.success is True
    assert fill_locator.filled == "Juandi"
    assert "sin enviarlo" in filled.message


@pytest.mark.asyncio
async def test_open_numbered_search_result_validates_and_navigates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage()
    page.url = "https://search.example/?q=jarvis"
    browser = controller(tmp_path, page, monkeypatch)

    result = await browser.open_result(1)

    assert result.success is True
    assert result.details["verified"] is True
    assert page.url == "https://result.example/demo"


@pytest.mark.asyncio
async def test_tab_lifecycle_uses_only_controlled_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakePage("Inicio")
    second = FakePage("Documentación GitHub")
    second.url = "https://github.com/docs"
    browser = controller(tmp_path, first, monkeypatch)
    browser._context = FakeContext([first, second])

    listed = await browser.list_tabs()
    switched = await browser.switch_tab("github")
    closed = await browser.close_tab()
    created = await browser.new_tab()

    assert listed.details["tabs"][1]["title"] == "Documentación GitHub"
    assert switched.success is True
    assert second.closed is True
    assert closed.success is True
    assert created.success is True
    assert browser._page.page_title == "Nueva pestaña"
