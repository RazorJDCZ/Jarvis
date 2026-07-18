from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.actions.catalog import ActionCatalog, ActionSecurityError
from jarvis.actions.models import ActionName, ActionPlan, ActionRisk, ActionSource, ExecutionResult


def catalog(tmp_path: Path) -> ActionCatalog:
    return ActionCatalog(tmp_path, "https://www.google.com/search?q={query}")


def test_every_declared_action_has_a_catalog_entry(tmp_path: Path) -> None:
    names = catalog(tmp_path).action_names

    assert len(names) == 47
    assert set(names) == {name.value for name in ActionName if name is not ActionName.WORKFLOW_RUN}


def test_static_application_is_low_risk(tmp_path: Path) -> None:
    action = catalog(tmp_path).prepare(ActionPlan(ActionName.APP_OPEN, {"app": "calculator"}))

    assert action.arguments == {"app": "calculator"}
    assert action.risk is ActionRisk.LOW


@pytest.mark.parametrize(
    ("spoken", "canonical"),
    [
        ("calculadora", "calculator"),
        ("bloc de notas", "notepad"),
        ("explorador de archivos", "explorer"),
        ("configuración", "settings"),
    ],
)
def test_catalog_normalizes_model_application_aliases(
    tmp_path: Path,
    spoken: str,
    canonical: str,
) -> None:
    action = catalog(tmp_path).prepare(ActionPlan(ActionName.APP_OPEN, {"app": spoken}))

    assert action.arguments == {"app": canonical}


def test_installed_start_menu_application_requires_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_catalog = catalog(tmp_path)
    shortcut = tmp_path / "Spotify.lnk"
    monkeypatch.setattr(action_catalog.apps, "resolve_shortcut", lambda _name: shortcut)

    action = action_catalog.prepare(ActionPlan(ActionName.APP_OPEN, {"app": "spotify"}))

    assert action.arguments["shortcut"] == str(shortcut)
    assert action.risk is ActionRisk.MEDIUM
    assert "Spotify" in action.description


@pytest.mark.parametrize("app", ["powershell", "unknown program", "../../cmd.exe"])
def test_unknown_applications_are_blocked(tmp_path: Path, app: str) -> None:
    with pytest.raises(ActionSecurityError, match="No encontré"):
        catalog(tmp_path).prepare(ActionPlan(ActionName.APP_OPEN, {"app": app}))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "https://example.com/"),
        ("www.example.com/path?q=1", "https://www.example.com/path?q=1"),
        ("https://example.com/demo", "https://example.com/demo"),
        ("http://127.0.0.1:8765", "http://127.0.0.1:8765/"),
        ("http://[::1]:8765/demo", "http://[::1]:8765/demo"),
    ],
)
def test_http_urls_are_normalized(tmp_path: Path, raw: str, expected: str) -> None:
    action = catalog(tmp_path).prepare(ActionPlan(ActionName.BROWSER_OPEN, {"url": raw}))

    assert action.arguments["url"] == expected


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///C:/secrets.txt",
        "data:text/html,hello",
        "https://user:password@example.com",
        "https://example.com:99999",
        "https://example.com:0",
        "https://example.com\nmalicious",
    ],
)
def test_unsafe_urls_are_blocked(tmp_path: Path, url: str) -> None:
    with pytest.raises(ActionSecurityError):
        catalog(tmp_path).prepare(ActionPlan(ActionName.BROWSER_OPEN, {"url": url}))


@pytest.mark.parametrize("level", [-1, 101, "alto", None, True])
def test_invalid_volume_levels_are_rejected(tmp_path: Path, level: object) -> None:
    with pytest.raises(ActionSecurityError):
        catalog(tmp_path).prepare(ActionPlan(ActionName.VOLUME_SET, {"level": level}))


def test_model_planned_mutation_is_escalated(tmp_path: Path) -> None:
    action = catalog(tmp_path).prepare(
        ActionPlan(
            ActionName.VOLUME_SET,
            {"level": 25},
            source=ActionSource.LOCAL_MODEL,
        )
    )
    read_only = catalog(tmp_path).prepare(
        ActionPlan(ActionName.WINDOW_LIST, source=ActionSource.LOCAL_MODEL)
    )

    assert action.risk is ActionRisk.MEDIUM
    assert read_only.risk is ActionRisk.LOW


def test_sensitive_actions_have_expected_risk(tmp_path: Path) -> None:
    action_catalog = catalog(tmp_path)

    assert (
        action_catalog.prepare(
            ActionPlan(ActionName.BROWSER_FILL, {"field": "Nombre", "text": "Juandi"})
        ).risk
        is ActionRisk.MEDIUM
    )
    assert (
        action_catalog.prepare(ActionPlan(ActionName.POINTER_CLICK, {"x": 50, "y": 50})).risk
        is ActionRisk.HIGH
    )
    assert (
        action_catalog.prepare(ActionPlan(ActionName.WINDOW_CLOSE, {"title": "Editor"})).risk
        is ActionRisk.MEDIUM
    )
    assert action_catalog.prepare(ActionPlan(ActionName.CLIPBOARD_READ)).risk is ActionRisk.MEDIUM
    assert (
        action_catalog.prepare(ActionPlan(ActionName.BROWSER_CLOSE_TAB)).risk is ActionRisk.MEDIUM
    )
    assert action_catalog.prepare(ActionPlan(ActionName.SCREENSHOT_TAKE)).risk is ActionRisk.MEDIUM
    assert action_catalog.prepare(ActionPlan(ActionName.SCREEN_DESCRIBE)).risk is ActionRisk.MEDIUM
    assert (
        action_catalog.prepare(ActionPlan(ActionName.SCREEN_CLICK, {"target": "Aceptar"})).risk
        is ActionRisk.HIGH
    )


@pytest.mark.parametrize(
    ("name", "target"),
    [
        (ActionName.BROWSER_CLICK, "Comprar ahora"),
        (ActionName.BROWSER_CLICK, "Enviar dinero"),
        (ActionName.UI_CLICK, "Eliminar todos los archivos"),
        (ActionName.UI_CLICK, "Delete account"),
        (ActionName.SCREEN_CLICK, "Confirmar compra"),
    ],
)
def test_destructive_or_financial_controls_are_blocked(
    tmp_path: Path,
    name: ActionName,
    target: str,
) -> None:
    with pytest.raises(ActionSecurityError, match="no lo activará"):
        catalog(tmp_path).prepare(ActionPlan(name, {"target": target}))


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        (ActionName.UI_HOTKEY, {"hotkey": "alt_f4"}),
        (ActionName.UI_TYPE, {"text": ""}),
        (ActionName.BROWSER_FILL, {"field": "x", "text": "a" * 1_001}),
        (ActionName.POINTER_SCROLL, {"amount": 0}),
        (ActionName.POINTER_CLICK, {"x": 50_000, "y": 1}),
        (ActionName.UI_KEY, {"key": "delete"}),
        (ActionName.CLIPBOARD_WRITE, {"text": "a" * 2_001}),
        (ActionName.BROWSER_OPEN_RESULT, {"index": 0}),
        (ActionName.BROWSER_OPEN_RESULT, {"index": 11}),
        (ActionName.SCREEN_ASK, {"question": ""}),
    ],
)
def test_argument_limits_are_enforced(
    tmp_path: Path,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ActionSecurityError):
        catalog(tmp_path).prepare(ActionPlan(name, arguments))


@pytest.mark.asyncio
async def test_visual_pointer_confirmation_uses_cursor_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_catalog = catalog(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        action_catalog.desktop,
        "click_if_cursor_unchanged",
        lambda _x, _y: calls.append("guarded") or ExecutionResult(True, "guarded"),
    )
    monkeypatch.setattr(
        action_catalog.desktop,
        "click",
        lambda _x, _y: calls.append("direct") or ExecutionResult(True, "direct"),
    )
    visual = action_catalog.prepare(
        ActionPlan(
            ActionName.POINTER_CLICK,
            {"x": 100, "y": 200},
            source=ActionSource.CONFIRMATION,
        )
    )
    explicit = action_catalog.prepare(
        ActionPlan(ActionName.POINTER_CLICK, {"x": 100, "y": 200})
    )

    await action_catalog.execute(visual)
    await action_catalog.execute(explicit)

    assert calls == ["guarded", "direct"]
