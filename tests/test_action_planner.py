from __future__ import annotations

import json

import httpx
import pytest

from jarvis.actions.models import ActionName, ActionSource, ActionWorkflowPlan
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings


def patch_httpx(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    original_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        content = json.dumps(payload)
        return httpx.Response(200, json={"message": {"content": content}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.planner.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )


@pytest.mark.asyncio
async def test_local_planner_returns_typed_allowlisted_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "volume.set",
            "arguments": {"level": 30},
            "confidence": 0.94,
        },
    )
    planner = LocalActionPlanner(Settings(), ("volume.set", "window.list"))

    result = await planner.plan("configura el sonido a treinta")

    assert result.name is ActionName.VOLUME_SET
    assert result.arguments == {"level": 30}
    assert result.source is ActionSource.LOCAL_MODEL


@pytest.mark.asyncio
async def test_local_planner_returns_bounded_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "none",
            "arguments": {},
            "steps": [
                {"action": "app.open", "arguments": {"name": "notepad"}},
                {"action": "ui.type", "arguments": {"content": "hola"}},
            ],
            "confidence": 0.96,
        },
    )
    planner = LocalActionPlanner(Settings(), ("app.open", "ui.type"))

    result = await planner.plan("abre notepad y escribe hola")

    assert isinstance(result, ActionWorkflowPlan)
    assert tuple(step.name for step in result.steps) == (
        ActionName.APP_OPEN,
        ActionName.UI_TYPE,
    )
    assert result.steps[0].arguments == {"app": "notepad"}
    assert result.steps[1].arguments == {"text": "hola"}
    assert all(step.source is ActionSource.LOCAL_MODEL for step in result.steps)


@pytest.mark.asyncio
async def test_local_planner_preserves_explicit_browser_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_httpx(
        monkeypatch,
        {
            "direct_request": True,
            "action": "browser.open",
            "arguments": {
                "website": "https://www.youtube.com",
                "navegador": "chrome",
            },
            "steps": [],
            "confidence": 0.96,
        },
    )
    planner = LocalActionPlanner(Settings(), ("browser.open",))

    result = await planner.plan("abre YouTube usando Chrome")

    assert result.name is ActionName.BROWSER_OPEN
    assert result.arguments == {
        "url": "https://www.youtube.com",
        "browser": "chrome",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"direct_request": False, "action": "none", "arguments": {}, "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": 0.2},
        {"direct_request": True, "action": "shell.run", "arguments": {}, "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": "bad", "confidence": 1},
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": True},
        {
            "direct_request": True,
            "action": "volume.set",
            "arguments": {},
            "confidence": float("nan"),
        },
        {"direct_request": True, "action": "volume.set", "arguments": {}, "confidence": 1.1},
    ],
)
async def test_local_planner_rejects_unsafe_or_uncertain_output(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    patch_httpx(monkeypatch, payload)
    planner = LocalActionPlanner(Settings(), ("volume.set",))

    assert await planner.plan("haz algo") is None


@pytest.mark.asyncio
async def test_planner_can_be_disabled_without_network() -> None:
    planner = LocalActionPlanner(
        Settings(action_model_planning=False),
        ("volume.set",),
    )

    assert await planner.plan("configura el volumen") is None
