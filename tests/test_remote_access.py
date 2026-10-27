from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from webauthn.helpers import bytes_to_base64url

from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.services.remote_access import (
    RemoteAccessError,
    RemoteAccessService,
    RemoteIdentity,
)


def remote_settings(tmp_path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "project_root": tmp_path,
        "brain_mode": "fallback",
        "action_model_planning": False,
        "memory_enabled": False,
        "voice_preload": False,
        "remote_access_enabled": True,
        "remote_origin": "https://jarvis.test-tail.ts.net",
        "remote_allowed_login": "owner@example.com",
    }
    values.update(overrides)
    return Settings(
        **values,
    )


def registration_verification() -> SimpleNamespace:
    return SimpleNamespace(
        credential_id=b"credential-id",
        credential_public_key=b"public-key",
        sign_count=0,
    )


def authentication_verification() -> SimpleNamespace:
    return SimpleNamespace(new_sign_count=1)


def test_remote_configuration_requires_private_https_origin(tmp_path) -> None:
    with pytest.raises(ValueError, match="origen HTTPS"):
        remote_settings(tmp_path, remote_origin="http://jarvis.example.com")

    settings = remote_settings(tmp_path)

    assert settings.remote_rp_id == "jarvis.test-tail.ts.net"
    assert settings.remote_cookie_secure is True
    assert settings.host == "127.0.0.1"
    assert settings.android_app_origin == (
        "android:apk-key-hash:Z4aWii5wK59A70iDyIi-23H4svK18BS1_f5_JuY9F3k"
    )
    assert settings.remote_webauthn_origins == [
        "https://jarvis.test-tail.ts.net",
        settings.android_app_origin,
    ]


def test_passkey_pairing_authentication_and_revocation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = remote_settings(tmp_path)
    service = RemoteAccessService(settings)
    identity = RemoteIdentity("owner@example.com", "Owner")
    pairing = service.start_pairing()
    options = service.begin_registration(pairing["code"], "Teléfono personal", identity)
    registration_arguments: dict[str, object] = {}

    def verify_registration(**kwargs: object) -> SimpleNamespace:
        registration_arguments.update(kwargs)
        return registration_verification()

    monkeypatch.setattr(
        "jarvis.services.remote_access.verify_registration_response",
        verify_registration,
    )

    device, session_token = service.finish_registration(
        options["ceremony_id"],
        {"response": {"transports": ["internal"]}},
        identity,
    )

    assert device["label"] == "Teléfono personal"
    assert registration_arguments["expected_origin"] == settings.remote_webauthn_origins
    assert service.authenticate(session_token, identity) is not None
    assert (
        service.authenticate(
            session_token,
            RemoteIdentity("attacker@example.com", "Attacker"),
        )
        is None
    )
    with pytest.raises(RemoteAccessError, match="no está autorizada"):
        service.begin_authentication(
            device["device_id"],
            RemoteIdentity("attacker@example.com", "Attacker"),
        )

    authentication = service.begin_authentication(None, identity)
    assert len(authentication["options"]["allowCredentials"]) == 1
    authentication_arguments: dict[str, object] = {}

    def verify_authentication(**kwargs: object) -> SimpleNamespace:
        authentication_arguments.update(kwargs)
        return authentication_verification()

    monkeypatch.setattr(
        "jarvis.services.remote_access.verify_authentication_response",
        verify_authentication,
    )
    refreshed, new_token = service.finish_authentication(
        authentication["ceremony_id"],
        {
            "rawId": bytes_to_base64url(b"credential-id"),
            "response": {},
        },
        identity,
    )

    assert refreshed["device_id"] == device["device_id"]
    assert authentication_arguments["expected_origin"] == settings.remote_webauthn_origins
    assert service.authenticate(new_token, identity).sign_count == 1

    restarted = RemoteAccessService(settings)
    assert restarted.authenticate(new_token, identity).device_id == device["device_id"]

    assert service.revoke_device(device["device_id"]) is True
    assert service.authenticate(new_token, identity) is None
    assert restarted.authenticate(new_token, identity) is None


def test_remote_logout_removes_persistent_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = remote_settings(tmp_path)
    service = RemoteAccessService(settings)
    identity = RemoteIdentity("owner@example.com", "Owner")
    pairing = service.start_pairing()
    options = service.begin_registration(pairing["code"], "Pixel personal", identity)
    monkeypatch.setattr(
        "jarvis.services.remote_access.verify_registration_response",
        lambda **_kwargs: registration_verification(),
    )
    _device, token = service.finish_registration(
        options["ceremony_id"],
        {"response": {"transports": ["internal"]}},
        identity,
    )

    assert RemoteAccessService(settings).authenticate(token, identity) is not None
    service.logout(token)
    assert RemoteAccessService(settings).authenticate(token, identity) is None


def test_pairing_code_expires_after_bounded_failures(tmp_path) -> None:
    service = RemoteAccessService(remote_settings(tmp_path))
    identity = RemoteIdentity("owner@example.com", "Owner")
    service.start_pairing()

    for _ in range(4):
        with pytest.raises(RemoteAccessError, match="inválido"):
            service.begin_registration("0000-0000", "Mi teléfono", identity)
    with pytest.raises(RemoteAccessError, match="Demasiados intentos"):
        service.begin_registration("0000-0000", "Mi teléfono", identity)


def test_remote_database_connections_release_the_file(tmp_path) -> None:
    settings = remote_settings(tmp_path)
    service = RemoteAccessService(settings)

    service.list_devices()
    service.recent_activity()
    moved_path = settings.remote_database_path.with_suffix(".closed.sqlite3")
    settings.remote_database_path.replace(moved_path)

    assert moved_path.exists()


def test_remote_api_requires_tailscale_and_passkey_then_escalates_actions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = remote_settings(tmp_path)
    app = create_app(settings)
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
        local_status = client.get("/api/remote/status")
        pairing = client.post("/api/remote/pairing/start")
        missing_identity = client.get(f"{remote_base}/api/health")

        assert local_status.json()["remote"] is False
        assert pairing.status_code == 200
        assert missing_identity.status_code == 403

        unauthenticated = client.get(
            f"{remote_base}/api/health",
            headers=remote_headers,
        )
        asset_links = client.get(
            f"{remote_base}/.well-known/assetlinks.json",
            headers=remote_headers,
        )
        registration = client.post(
            f"{remote_base}/api/remote/pair/options",
            headers=remote_headers,
            json={"code": pairing.json()["code"], "label": "Pixel personal"},
        )
        verified = client.post(
            f"{remote_base}/api/remote/pair/verify",
            headers=remote_headers,
            json={
                "ceremony_id": registration.json()["ceremony_id"],
                "credential": {"response": {"transports": ["internal"]}},
            },
        )
        discoverable_authentication = client.post(
            f"{remote_base}/api/remote/auth/options",
            headers=remote_headers,
            json={},
        )

        assert unauthenticated.status_code == 401
        assert asset_links.status_code == 200
        assert asset_links.headers["content-type"].startswith("application/json")
        assert asset_links.json() == [
            {
                "relation": [
                    "delegate_permission/common.handle_all_urls",
                    "delegate_permission/common.get_login_creds",
                ],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.android_package_name,
                    "sha256_cert_fingerprints": [
                        settings.android_certificate_sha256,
                    ],
                },
            }
        ]
        assert registration.status_code == 200
        assert verified.status_code == 200
        assert verified.json()["authenticated"] is True
        assert discoverable_authentication.status_code == 200
        assert len(discoverable_authentication.json()["options"]["allowCredentials"]) == 1

        pending = client.post(
            f"{remote_base}/api/chat",
            headers=remote_headers,
            json={"message": "abre la calculadora", "session_id": "mobile-session"},
        )
        restored = client.post(
            f"{remote_base}/api/remote/session",
            headers=remote_headers,
            json={"session_id": "mobile-session"},
        )

        assert pending.status_code == 200
        assert pending.json()["action"]["status"] == "pending"
        assert "Autorizar desde el celular" in pending.json()["action"]["description"]
        assert restored.json()["action"]["action_id"] == pending.json()["action"]["action_id"]

        stopped = client.post(
            f"{remote_base}/api/remote/stop",
            headers=remote_headers,
            json={"session_id": "mobile-session"},
        )
        no_longer_pending = client.post(
            f"{remote_base}/api/remote/session",
            headers=remote_headers,
            json={"session_id": "mobile-session"},
        )
        remote_audit = client.get(
            f"{remote_base}/api/actions/audit",
            headers=remote_headers,
        )
        wrong_origin = client.post(
            f"{remote_base}/api/remote/stop",
            headers={**remote_headers, "Origin": "https://evil.example"},
            json={"session_id": "mobile-session"},
        )
        revoked = client.delete(
            f"/api/remote/devices/{verified.json()['device']['device_id']}",
        )
        rejected_after_revocation = client.get(
            f"{remote_base}/api/health",
            headers=remote_headers,
        )

        assert stopped.json()["stopped"] is True
        assert stopped.json()["pending_actions"] == 1
        assert no_longer_pending.json()["action"] is None
        assert remote_audit.status_code == 403
        assert wrong_origin.status_code == 403
        assert revoked.status_code == 200
        assert rejected_after_revocation.status_code == 401
