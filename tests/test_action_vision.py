from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.models import ActionName, ActionPlan, ExecutionResult
from jarvis.actions.vision import LocalVisionController, ScreenCapture, ScreenMonitor
from jarvis.config import Settings


def capture(_monitor: str = "all") -> ScreenCapture:
    return ScreenCapture(
        encoded_png="cG5n",
        left=-100,
        top=0,
        width=2_000,
        height=1_000,
    )


@pytest.mark.asyncio
async def test_describe_returns_structured_local_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monkeypatch.setattr(controller, "_capture", capture)
    monkeypatch.setattr(
        controller,
        "monitors",
        lambda: (ScreenMonitor("1", r"\\.\DISPLAY1", 0, 0, 1920, 1080, True),),
    )

    async def response(*_args: object) -> dict[str, object]:
        return {
            "summary": "Hay un editor abierto.",
            "visible_apps": ["Bloc de notas"],
            "important_text": ["Documento nuevo"],
            "interactive_elements": ["Guardar", "Cerrar"],
            "warnings": [],
        }

    monkeypatch.setattr(controller, "_request", response)

    result = await controller.describe()

    assert result.success is True
    assert "editor abierto" in result.message
    assert result.details["ephemeral_capture"] is True
    assert result.details["interactive_elements"] == ["Guardar", "Cerrar"]


@pytest.mark.asyncio
async def test_describe_all_analyzes_each_monitor_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    captures = {
        "1": ScreenCapture(
            "b25l", 0, 0, 1920, 1080, "1", "Monitor 1 (principal)",
            r"\\.\DISPLAY1", "izquierda", 1024, 576, "one",
        ),
        "2": ScreenCapture(
            "dHdv", 1920, 0, 1920, 1080, "2", "Monitor 2",
            r"\\.\DISPLAY2", "derecha", 1024, 576, "two",
        ),
    }
    monitors = (
        ScreenMonitor("1", r"\\.\DISPLAY1", 0, 0, 1920, 1080, True),
        ScreenMonitor("2", r"\\.\DISPLAY2", 1920, 0, 1920, 1080),
    )
    monkeypatch.setattr(controller, "monitors", lambda: monitors)
    monkeypatch.setattr(controller, "_capture", lambda monitor="all": captures[monitor])
    requested: list[str] = []

    async def response(_prompt, _schema, screen_capture, _max_tokens):
        requested.append(screen_capture.monitor)
        return {
            "summary": f"Contenido exclusivo {screen_capture.monitor}",
            "visible_apps": [f"Aplicación {screen_capture.monitor}"],
            "important_text": [],
            "interactive_elements": [],
            "warnings": [],
        }

    monkeypatch.setattr(controller, "_request", response)

    result = await controller.describe("all")

    assert result.success is True
    assert requested == ["1", "2"]
    assert result.details["monitor"] == "all"
    assert len(result.details["monitor_observations"]) == 2
    assert "Monitor 1" in result.message and "Monitor 2" in result.message


@pytest.mark.asyncio
async def test_find_maps_normalized_coordinates_to_virtual_desktop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monkeypatch.setattr(controller, "_capture", capture)

    async def response(*_args: object) -> dict[str, object]:
        return {
            "found": True,
            "x": 500,
            "y": 250,
            "confidence": 0.94,
            "element": "Botón Aceptar",
            "dangerous": False,
            "reason": "Coincidencia clara",
        }

    monkeypatch.setattr(controller, "_request", response)

    result = await controller.find("Aceptar")

    assert result.success is True
    assert result.details["x"] == 900
    assert result.details["y"] == 250
    assert result.details["confidence"] == 0.94


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {
            "found": True,
            "x": 500,
            "y": 250,
            "confidence": 0.4,
            "element": "Parecido",
            "dangerous": False,
            "reason": "Dudoso",
        },
        {
            "found": True,
            "x": True,
            "y": 250,
            "confidence": 0.99,
            "element": "Inválido",
            "dangerous": False,
            "reason": "Inválido",
        },
    ],
)
async def test_find_rejects_low_confidence_or_invalid_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monkeypatch.setattr(controller, "_capture", capture)

    async def model_response(*_args: object) -> dict[str, object]:
        return response

    monkeypatch.setattr(controller, "_request", model_response)

    result = await controller.find("objetivo")

    assert result.success is False


@pytest.mark.asyncio
async def test_vision_refuses_non_loopback_ollama(tmp_path: Path) -> None:
    controller = LocalVisionController(
        Settings(project_root=tmp_path, ollama_url="https://remote.example")
    )

    result = await controller.status()

    assert result.success is False
    assert "esta computadora" in result.message


@pytest.mark.asyncio
async def test_status_requires_declared_vision_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"capabilities": ["completion", "vision"]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.vision.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    controller = LocalVisionController(Settings(project_root=tmp_path))

    result = await controller.status()

    assert result.success is True
    assert result.details == {"local": True, "vision": True}


@pytest.mark.asyncio
async def test_visual_model_is_reused_during_request_then_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.AsyncClient
    requests: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "Minecraft está visible.",
                                "visible_apps": ["Minecraft"],
                                "important_text": [],
                                "interactive_elements": [],
                                "warnings": [],
                            }
                        )
                    }
                },
            )
        return httpx.Response(200, json={"done": True})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "jarvis.actions.vision.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monkeypatch.setattr(
        controller,
        "_capture",
        lambda _monitor="1": ScreenCapture(
            "cG5n", 0, 0, 1920, 1080, "1", "Monitor 1", image_width=1024,
            image_height=576,
        ),
    )

    result = await controller.describe("1")

    assert result.success is True
    assert requests[0][0] == "/api/chat"
    assert requests[0][1]["keep_alive"] == "2m"
    assert requests[1] == (
        "/api/generate",
        {"model": "qwen3.5:4b", "keep_alive": 0},
    )


class FakeVision:
    def __init__(self, *, dangerous: bool = False) -> None:
        self.dangerous = dangerous

    async def find(self, target: str, monitor: str = "all") -> ExecutionResult:
        return ExecutionResult(
            True,
            "Localizado",
            {
                "target": target,
                "element": "Icono objetivo",
                "x": 400,
                "y": 300,
                "confidence": 0.95,
                "dangerous": self.dangerous,
                "monitor": monitor,
                "monitor_label": f"Monitor {monitor}",
            },
        )


def test_monitor_selector_supports_number_position_and_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monitors = (
        ScreenMonitor("1", r"\\.\DISPLAY1", 0, 0, 1920, 1080, True),
        ScreenMonitor("2", r"\\.\DISPLAY2", 1920, 0, 2560, 1440),
    )
    monkeypatch.setattr(controller, "monitors", lambda: monitors)

    assert controller.resolve_monitor("principal") == monitors[0]
    assert controller.resolve_monitor("monitor 2") == monitors[1]
    assert controller.resolve_monitor("derecha") == monitors[1]
    assert controller.resolve_monitor("izquierda") == monitors[0]
    assert controller.resolve_monitor("todas las pantallas") is None
    with pytest.raises(ValueError, match="detecté: Monitor 1"):
        controller.resolve_monitor("monitor 9")


def test_list_monitors_returns_safe_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    monitors = (
        ScreenMonitor("1", r"\\.\DISPLAY1", -1920, 0, 1920, 1080),
        ScreenMonitor("2", r"\\.\DISPLAY2", 0, 0, 2560, 1440, True),
    )
    monkeypatch.setattr(controller, "monitors", lambda: monitors)

    result = controller.list_monitors()

    assert result.success is True
    assert result.details["monitors"][1]["primary"] is True
    assert "Monitor 2 (principal)" in result.message


@pytest.mark.asyncio
async def test_describe_uses_selected_monitor_and_reports_focus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = LocalVisionController(Settings(project_root=tmp_path))
    captured: list[str] = []

    def selected_capture(monitor: str = "all") -> ScreenCapture:
        captured.append(monitor)
        return ScreenCapture(
            "cG5n",
            1920,
            0,
            2560,
            1440,
            monitor="2",
            monitor_label="Monitor 2",
        )

    async def response(*_args: object) -> dict[str, object]:
        return {
            "summary": "Hay un navegador.",
            "visible_apps": ["Chrome"],
            "important_text": [],
            "interactive_elements": [],
            "warnings": [],
        }

    monkeypatch.setattr(controller, "_capture", selected_capture)
    monkeypatch.setattr(controller, "_request", response)

    result = await controller.describe("2")

    assert result.success is True
    assert captured == ["2"]
    assert result.details["monitor"] == "2"
    assert result.details["monitor_label"] == "Monitor 2"


@pytest.mark.asyncio
async def test_visual_click_prefers_accessibility_before_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(project_root=tmp_path)
    action_catalog = ActionCatalog(tmp_path, settings.browser_search_url, settings)
    action_catalog.vision = FakeVision()
    monkeypatch.setattr(
        action_catalog.windows,
        "click_control",
        lambda _target: ExecutionResult(True, "Control activado"),
    )
    pixel_clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(
        action_catalog.desktop,
        "click",
        lambda x, y: pixel_clicks.append((x, y)) or ExecutionResult(True, "Clic"),
    )
    action = action_catalog.prepare(
        ActionPlan(ActionName.SCREEN_CLICK, {"target": "Configuración"})
    )

    result = await action_catalog.execute(action)

    assert result.success is True
    assert result.details["method"] == "accessibility"
    assert pixel_clicks == []


@pytest.mark.asyncio
async def test_visual_click_never_activates_model_flagged_danger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(project_root=tmp_path)
    action_catalog = ActionCatalog(tmp_path, settings.browser_search_url, settings)
    action_catalog.vision = FakeVision(dangerous=True)
    monkeypatch.setattr(
        action_catalog.windows,
        "click_control",
        lambda _target: ExecutionResult(False, "No accesible"),
    )
    pixel_clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(
        action_catalog.desktop,
        "click",
        lambda x, y: pixel_clicks.append((x, y)) or ExecutionResult(True, "Clic"),
    )
    action = action_catalog.prepare(ActionPlan(ActionName.SCREEN_CLICK, {"target": "Aceptar"}))

    result = await action_catalog.execute(action)

    assert result.success is False
    assert pixel_clicks == []


@pytest.mark.asyncio
async def test_visual_pixel_fallback_only_moves_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(project_root=tmp_path)
    action_catalog = ActionCatalog(tmp_path, settings.browser_search_url, settings)
    action_catalog.vision = FakeVision()
    monkeypatch.setattr(
        action_catalog.windows,
        "click_control",
        lambda _target: ExecutionResult(False, "No accesible"),
    )
    moves: list[tuple[int, int]] = []
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(
        action_catalog.desktop,
        "move",
        lambda x, y: moves.append((x, y)) or ExecutionResult(True, "Cursor movido"),
    )
    monkeypatch.setattr(
        action_catalog.desktop,
        "click",
        lambda x, y: clicks.append((x, y)) or ExecutionResult(True, "Clic"),
    )
    action = action_catalog.prepare(ActionPlan(ActionName.SCREEN_CLICK, {"target": "Aceptar"}))

    result = await action_catalog.execute(action)

    assert result.success is True
    assert result.details["pixel_confirmation_required"] is True
    assert moves == [(400, 300)]
    assert clicks == []
