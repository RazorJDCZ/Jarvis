from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.services.remote_access import RemoteIdentity


def api_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "project_root": tmp_path,
        "brain_mode": "fallback",
        "memory_enabled": False,
        "information_verification_enabled": False,
        "action_model_planning": False,
        "ollama_warmup_enabled": False,
        "attachment_max_bytes": 1_024,
        "steam_roots": str(tmp_path / "no-steam"),
        "epic_manifest_roots": str(tmp_path / "no-epic"),
    }
    values.update(overrides)
    return Settings(**values)


def app_without_background_hardware(settings: Settings):
    app = create_app(settings)
    suite = app.state.action_engine.capabilities
    assert suite is not None
    suite.start = AsyncMock()
    suite.close = AsyncMock()
    suite.vision.analyze_image_bytes = AsyncMock(
        side_effect=AssertionError("Una carga no debe activar cámara o visión")
    )
    return app, suite


def test_capability_api_uploads_reminders_traces_permissions_and_isolation(
    tmp_path: Path,
) -> None:
    app, suite = app_without_background_hardware(api_settings(tmp_path))

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/attachments",
            data={"session_id": "owner", "source": "file"},
            files={"file": ("../../notes.txt", b"contenido privado", "text/plain")},
        )
        attachment_id = uploaded.json()["attachment"]["attachment_id"]
        owner_files = client.get("/api/attachments?session_id=owner")
        other_files = client.get("/api/attachments?session_id=other")
        oversized = client.post(
            "/api/attachments",
            data={"session_id": "owner"},
            files={"file": ("large.txt", b"x" * 1_025, "text/plain")},
        )
        reminder = client.post(
            "/api/reminders",
            json={
                "session_id": "owner",
                "title": "Entrega",
                "due": "2099-01-01T09:00:00-05:00",
                "recurrence": "none",
            },
        )
        owner_reminders = client.get("/api/reminders?session_id=owner")
        other_reminders = client.get("/api/reminders?session_id=other")
        permission = client.patch(
            "/api/permissions/media.play_pause",
            json={"decision": "allow", "remote": False},
        )
        excessive_permission = client.patch(
            "/api/permissions/media.play_pause",
            json={
                "decision": "allow",
                "remote": False,
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        chat = client.post(
            "/api/chat",
            json={"message": "Hola Jarvis", "session_id": "owner"},
        )
        trace_id = chat.json()["trace_id"]
        trace = client.get(f"/api/traces/{trace_id}?session_id=owner")
        hidden_trace = client.get(f"/api/traces/{trace_id}?session_id=other")
        deleted = client.delete(f"/api/attachments/{attachment_id}?session_id=owner")

    assert uploaded.status_code == 200
    assert uploaded.json()["attachment"]["original_name"] == "notes.txt"
    assert len(owner_files.json()["attachments"]) == 1
    assert other_files.json()["attachments"] == []
    assert oversized.status_code == 413
    assert reminder.status_code == 200
    assert len(owner_reminders.json()["reminders"]) == 1
    assert other_reminders.json()["reminders"] == []
    assert permission.status_code == 200
    assert excessive_permission.status_code == 400
    expiry = permission.json()["permission"]["expires_at"]
    assert expiry is not None and datetime.fromisoformat(expiry).year < 2099
    assert chat.status_code == 200 and trace_id
    assert trace.status_code == 200
    assert hidden_trace.status_code == 404
    assert deleted.json() == {"deleted": True}
    assert suite.vision.analyze_image_bytes.await_count == 0


def registration_verification() -> SimpleNamespace:
    return SimpleNamespace(
        credential_id=b"credential-id",
        credential_public_key=b"public-key",
        sign_count=0,
    )


def test_remote_capability_sessions_cannot_collide_with_local_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = api_settings(
        tmp_path,
        remote_access_enabled=True,
        remote_origin="https://jarvis.test-tail.ts.net",
        remote_allowed_login="owner@example.com",
    )
    app, _suite = app_without_background_hardware(settings)
    monkeypatch.setattr(
        "jarvis.services.remote_access.verify_registration_response",
        lambda **_kwargs: registration_verification(),
    )
    remote_base = "https://jarvis.test-tail.ts.net"
    remote_headers = {
        "Origin": remote_base,
        "Tailscale-User-Login": "owner@example.com",
        "Tailscale-User-Name": "Owner",
    }

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        pairing = client.post("/api/remote/pairing/start").json()
        registration = client.post(
            f"{remote_base}/api/remote/pair/options",
            headers=remote_headers,
            json={"code": pairing["code"], "label": "Pixel personal"},
        ).json()
        verified = client.post(
            f"{remote_base}/api/remote/pair/verify",
            headers=remote_headers,
            json={
                "ceremony_id": registration["ceremony_id"],
                "credential": {"response": {"transports": ["internal"]}},
            },
        )
        assert verified.status_code == 200

        remote_upload = client.post(
            f"{remote_base}/api/attachments",
            headers=remote_headers,
            data={"session_id": "shared"},
            files={"file": ("remote.txt", b"solo remoto", "text/plain")},
        )
        remote_list = client.get(
            f"{remote_base}/api/attachments?session_id=shared",
            headers=remote_headers,
        )
        local_list = client.get("/api/attachments?session_id=shared")
        remote_chat = client.post(
            f"{remote_base}/api/chat",
            headers=remote_headers,
            json={"message": "Hola Jarvis", "session_id": "shared"},
        )
        trace_id = remote_chat.json()["trace_id"]
        remote_trace = client.get(
            f"{remote_base}/api/traces/{trace_id}?session_id=shared",
            headers=remote_headers,
        )
        local_trace = client.get(f"/api/traces/{trace_id}?session_id=shared")
        forbidden_permission = client.patch(
            f"{remote_base}/api/permissions/media.play_pause",
            headers=remote_headers,
            json={"decision": "allow", "remote": True},
        )

    assert remote_upload.status_code == 200
    assert len(remote_list.json()["attachments"]) == 1
    assert local_list.json()["attachments"] == []
    assert remote_chat.status_code == 200
    assert remote_trace.status_code == 200
    assert local_trace.status_code == 404
    assert forbidden_permission.status_code == 403


def test_remote_identity_type_is_stable_for_test_contract() -> None:
    identity = RemoteIdentity("owner@example.com", "Owner")

    assert identity.login == "owner@example.com"
