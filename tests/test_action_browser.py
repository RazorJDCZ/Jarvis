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

    async def page_factory() -> FakePage:
        return browser._page

    monkeypatch.setattr(browser, "_ensure_page", page_factory)
    return browser


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
