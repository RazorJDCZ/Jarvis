from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from jarvis.capabilities.connectors import (
    AppaConnector,
    ConnectorError,
    ConnectorRegistry,
    LocalTaskConnector,
    UnavailableTaskConnector,
    load_appa_bridge_descriptor,
)

APPA_CAPABILITIES = [
    "tasks.read",
    "tasks.write",
    "projects.read",
    "projects.write",
    "calendar.read",
    "calendar.write",
    "agenda.read",
    "inbox.read",
    "inbox.write",
    "focus.read",
    "focus.write",
]


def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "appa-jarvis-bridge",
        "api_version": "v1",
        "capabilities": APPA_CAPABILITIES,
    }


def descriptor_payload(token: str, port: int = 47_651) -> dict[str, object]:
    return {
        "schema_version": 1,
        "enabled": True,
        "host": "127.0.0.1",
        "port": port,
        "base_url": f"http://127.0.0.1:{port}/v1",
        "token": token,
        "api_version": "v1",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def write_descriptor(path: Path, token: str, port: int = 47_651) -> None:
    path.write_text(json.dumps(descriptor_payload(token, port)), encoding="utf-8")
    path.chmod(0o600)


@pytest.mark.asyncio
async def test_local_tasks_are_persistent_and_session_isolated(tmp_path: Path) -> None:
    path = tmp_path / "tasks.sqlite3"
    connector = LocalTaskConnector(path)
    created = await connector.create_task(
        "owner",
        "Preparar exposición",
        "Usar las diapositivas finales",
        "2026-08-12",
        priority="alta",
        category="universidad",
        reminder_at="2026-08-12T14:00:00+00:00",
    )
    await connector.create_task("other", "Tarea privada")

    assert [item.task_id for item in await connector.list_tasks("owner")] == [created.task_id]
    assert all(item.title != "Tarea privada" for item in await connector.list_tasks("owner"))
    with pytest.raises(ConnectorError, match="otra sesión"):
        await connector.complete_task("other", created.task_id)

    completed = await connector.complete_task("owner", created.task_id)

    assert completed.completed is True
    assert completed.priority == "alta"
    assert completed.category == "universidad"
    assert await connector.list_tasks("owner") == []
    assert (await connector.list_tasks("owner", include_completed=True))[0].completed is True
    assert len(await LocalTaskConnector(path).list_tasks("owner", include_completed=True)) == 1


@pytest.mark.asyncio
async def test_local_task_validation_never_interprets_title_as_a_path(tmp_path: Path) -> None:
    connector = LocalTaskConnector(tmp_path / "tasks.sqlite3")
    task = await connector.create_task("owner", "../../esto es solo un título")

    assert task.title == "../../esto es solo un título"
    assert not (tmp_path.parent / "esto es solo un título").exists()
    with pytest.raises(ConnectorError):
        await connector.create_task("owner", "x" * 301)


def patch_appa_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> list[dict[str, object]]:
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    client_options: list[dict[str, object]] = []

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        client_options.append(dict(kwargs))
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr("jarvis.capabilities.connectors.httpx.AsyncClient", client_factory)
    return client_options


@pytest.mark.asyncio
async def test_appa_contract_uses_bounded_rest_calls_and_bearer_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del tmp_path
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json=health())
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Desde Appa",
                            "completed": False,
                            "created_at": "2026-08-10T12:00:00Z",
                        }
                    ]
                },
            )
        if request.method == "POST":
            payload = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": "task-2",
                    "title": payload["title"],
                    "notes": payload["notes"],
                    "due": payload["due"],
                    "completed": False,
                },
            )
        return httpx.Response(
            200,
            json={"id": "task-1", "title": "Desde Appa", "completed": True},
        )

    client_options = patch_appa_transport(monkeypatch, handler)
    appa = AppaConnector("https://appa.example", "private-token", timeout=0.1)

    status = await appa.status()
    listed = await appa.list_tasks("owner")
    created = await appa.create_task("owner", "Nueva", "Notas", "2026-08-12")
    completed = await appa.complete_task("owner", "task-1")

    assert status["available"] is True
    assert listed[0].source == "appa"
    assert created.title == "Nueva"
    assert completed.completed is True
    assert [request.url.path for request in requests] == [
        "/health",
        "/tasks",
        "/tasks",
        "/tasks/task-1",
    ]
    assert all(request.headers["Authorization"] == "Bearer private-token" for request in requests)
    assert requests[2].headers.get("Idempotency-Key")
    assert appa.timeout == 2.0
    assert client_options[0]["follow_redirects"] is False
    assert client_options[0]["trust_env"] is False
    await appa.close()


@pytest.mark.asyncio
async def test_appa_failure_is_honest_and_registry_keeps_local_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    patch_appa_transport(monkeypatch, offline)
    appa = AppaConnector("http://127.0.0.1:9000", "")
    registry = ConnectorRegistry(LocalTaskConnector(tmp_path / "tasks.sqlite3"), appa)

    status = await appa.status()

    assert status["available"] is False
    assert registry.tasks is appa
    with pytest.raises(ConnectorError, match="no responde"):
        await registry.tasks.list_tasks("owner")
    with pytest.raises(ConnectorError, match="HTTPS"):
        AppaConnector("http://appa.example", "")
    await registry.close()


@pytest.mark.asyncio
async def test_appa_rejects_malformed_task_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_appa_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=health()
            if request.url.path == "/health"
            else {"tasks": [{"id": "missing-title"}]},
        ),
    )

    connector = AppaConnector("https://appa.example", "")
    with pytest.raises(ConnectorError, match="incompleta"):
        await connector.list_tasks("owner")
    await connector.close()


@pytest.mark.asyncio
async def test_appa_extended_contract_is_typed_idempotent_and_local_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content) if request.content else {}
        path = request.url.path.removeprefix("/v1")
        if path == "/health":
            return httpx.Response(200, json=health())
        if path == "/projects" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "projects": [
                        {
                            "id": "project-1",
                            "name": "Jarvis",
                            "description": "Asistente local",
                            "status": "active",
                            "target_date": "2026-12-01T23:59:00-05:00",
                            "created_at": "2026-08-10T12:00:00Z",
                            "updated_at": "2026-08-10T12:00:00Z",
                        }
                    ]
                },
            )
        if path == "/projects":
            return httpx.Response(
                201,
                json={
                    "id": "project-2",
                    "name": payload["name"],
                    "description": payload["description"],
                    "status": "active",
                    "target_date": payload["target_date"],
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if path == "/calendar/events" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "event-1",
                            "title": "Revisión",
                            "description": "",
                            "start_at": "2026-08-12T14:00:00+00:00",
                            "end_at": None,
                            "source_type": "manual",
                            "source_id": None,
                            "completed": False,
                            "created_at": "2026-08-10T12:00:00Z",
                            "updated_at": "2026-08-10T12:00:00Z",
                        }
                    ]
                },
            )
        if path == "/calendar/events":
            return httpx.Response(
                201,
                json={
                    "id": "event-2",
                    "title": payload["title"],
                    "description": payload["description"],
                    "start_at": payload["start_at"],
                    "end_at": payload["end_at"],
                    "source_type": "manual",
                    "source_id": None,
                    "completed": False,
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if path == "/inbox" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if path == "/inbox":
            assert payload == {"text": "Idea privada"}
            return httpx.Response(
                201,
                json={
                    "id": "inbox-1",
                    "text": payload["text"],
                    "source": "jarvis",
                    "archived": False,
                    "created_at": "2026-08-10T12:00:00Z",
                    "updated_at": "2026-08-10T12:00:00Z",
                },
            )
        if path == "/focus" and request.method == "GET":
            return httpx.Response(200, json={"sessions": []})
        if path == "/focus":
            return httpx.Response(
                201,
                json={
                    "id": "focus-1",
                    "task_id": payload["task_id"],
                    "task_title": payload["task_title"],
                    "duration_minutes": payload["duration_minutes"],
                    "remaining_seconds": payload["duration_minutes"] * 60,
                    "status": "active",
                    "started_at": "2026-08-10T12:00:00Z",
                    "planned_end_at": "2026-08-10T12:25:00Z",
                    "completed": False,
                },
            )
        raise AssertionError(f"Ruta inesperada: {request.method} {request.url.path}")

    patch_appa_transport(monkeypatch, handler)
    appa = AppaConnector("http://127.0.0.1:47651/v1", "a" * 40)

    assert (await appa.list_projects())[0].name == "Jarvis"
    assert (
        await appa.create_project("Appa", "Proyecto local", "2026-12-01")
    ).target_date == "2026-12-01"
    assert (await appa.list_calendar())[0].title == "Revisión"
    assert (
        await appa.create_calendar_event(
            "Demo",
            "2026-08-12T14:00:00+00:00",
            end_at="2026-08-12T15:00:00+00:00",
        )
    ).title == "Demo"
    assert await appa.list_inbox() == []
    assert (await appa.capture_inbox("Idea privada")).source == "jarvis"
    assert await appa.focus_status() is None
    assert (await appa.start_focus(25, task_title="Preparar demo")).status == "active"

    mutations = [request for request in requests if request.method == "POST"]
    assert len(mutations) == 4
    assert all(request.headers.get("Idempotency-Key") for request in mutations)
    assert all(request.url.host == "127.0.0.1" for request in requests)
    await appa.close()


@pytest.mark.parametrize(
    "mutation",
    [
        {"host": "example.com", "base_url": "https://example.com/v1"},
        {"port": True},
        {"token": "short"},
        {"base_url": "http://127.0.0.1:47651/v1/../admin"},
        {"generated_at": "2026-08-10T12:00:00"},
    ],
)
def test_appa_descriptor_rejects_untrusted_contracts(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    path = tmp_path / "jarvis-bridge.json"
    payload = {**descriptor_payload("a" * 40), **mutation}
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ConnectorError):
        load_appa_bridge_descriptor(path)


def test_appa_descriptor_rejects_links_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_text(json.dumps(descriptor_payload("a" * 40)), encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "jarvis-bridge.json"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("Este entorno no permite crear enlaces simbólicos")

    with pytest.raises(ConnectorError, match="enlace"):
        load_appa_bridge_descriptor(link)


@pytest.mark.asyncio
async def test_registry_discovers_appa_lazily_and_rotates_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorizations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers.get("Authorization", ""))
        if request.url.path == "/v1/health":
            return httpx.Response(200, json=health())
        return httpx.Response(200, json={"tasks": []})

    patch_appa_transport(monkeypatch, handler)
    descriptor = tmp_path / "jarvis-bridge.json"
    local = LocalTaskConnector(tmp_path / "tasks.sqlite3")
    registry = ConnectorRegistry(
        local,
        bridge_config_path=descriptor,
        bridge_database_marker=tmp_path / "appa.db",
    )

    assert registry.tasks is local
    write_descriptor(descriptor, "a" * 40)
    assert isinstance(registry.tasks, AppaConnector)
    await registry.tasks.list_tasks("owner")

    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps(descriptor_payload("b" * 40)), encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, descriptor)
    assert isinstance(registry.tasks, AppaConnector)
    await registry.tasks.list_tasks("owner")

    assert "Bearer " + "a" * 40 in authorizations
    assert "Bearer " + "b" * 40 in authorizations
    status_text = str(await registry.statuses())
    assert "a" * 40 not in status_text
    assert "b" * 40 not in status_text
    await registry.close()


@pytest.mark.asyncio
async def test_registry_never_falls_back_when_appa_is_installed_but_offline(
    tmp_path: Path,
) -> None:
    local = LocalTaskConnector(tmp_path / "tasks.sqlite3")
    marker = tmp_path / "appa.db"
    marker.touch()
    registry = ConnectorRegistry(
        local,
        bridge_config_path=tmp_path / "jarvis-bridge.json",
        bridge_database_marker=marker,
    )

    assert isinstance(registry.tasks, UnavailableTaskConnector)
    with pytest.raises(ConnectorError, match="puente privado"):
        await registry.tasks.create_task("owner", "No debe ir al fallback")
    assert await local.list_tasks("owner") == []


@pytest.mark.asyncio
async def test_registry_blocks_automatic_switch_when_local_tasks_exist(
    tmp_path: Path,
) -> None:
    local = LocalTaskConnector(tmp_path / "tasks.sqlite3")
    await local.create_task("owner", "Conservar en Jarvis")
    descriptor = tmp_path / "jarvis-bridge.json"
    write_descriptor(descriptor, "a" * 40)
    registry = ConnectorRegistry(local, bridge_config_path=descriptor)

    assert isinstance(registry.tasks, UnavailableTaskConnector)
    with pytest.raises(ConnectorError, match="dividir tus datos"):
        await registry.tasks.list_tasks("owner")
    assert (await local.list_tasks("owner"))[0].title == "Conservar en Jarvis"


@pytest.mark.asyncio
async def test_focus_status_recalculates_live_remaining_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_end = datetime.now(UTC) + timedelta(minutes=7)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json=health())
        return httpx.Response(
            200,
            json={
                "sessions": [
                    {
                        "id": "focus-live",
                        "task_id": None,
                        "task_title": "Prueba",
                        "duration_minutes": 25,
                        "remaining_seconds": 1_500,
                        "status": "active",
                        "started_at": datetime.now(UTC).isoformat(),
                        "planned_end_at": planned_end.isoformat(),
                        "completed": False,
                    }
                ]
            },
        )

    patch_appa_transport(monkeypatch, handler)
    appa = AppaConnector("http://127.0.0.1:47651/v1", "a" * 40)

    focus = await appa.focus_status()

    assert focus is not None
    assert 415 <= focus.remaining_seconds <= 420
    await appa.close()
