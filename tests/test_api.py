from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from jarvis.config import Settings
from jarvis.main import create_app, safe_audio_suffix, valid_session_id


def fallback_settings(**overrides: object) -> Settings:
    return Settings(
        brain_mode="fallback",
        safe_actions_enabled=False,
        **overrides,
    )


def test_health_and_ui_are_available() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        health = client.get("/api/health")
        index = client.get("/")
        manifest = client.get("/manifest.webmanifest")
        service_worker = client.get("/service-worker.js")
        icon = client.get("/static/icon.svg")
        openapi = client.get("/api/openapi.json")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["brain"]["available"] is True
    assert index.status_code == 200
    assert "JARVIS // Local Core" in index.text
    assert manifest.status_code == 200
    assert service_worker.status_code == 200
    assert "javascript" in service_worker.headers["content-type"]
    assert icon.status_code == 200
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "Jarvis Local Core"
    assert index.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in index.headers["content-security-policy"]


def test_fallback_conversation() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "Hola Jarvis", "session_id": "test"},
        )

    assert response.status_code == 200
    assert response.json()["provider"] == "fallback"
    assert "Juandi" in response.json()["response"]


def test_safe_command_uses_deterministic_provider() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "¿Qué hora es?", "session_id": "safe-test"},
        )

    assert response.status_code == 200
    assert response.json()["provider"] == "safe-command"
    assert response.json()["response"].startswith("Son las ")


def test_cross_origin_browser_request_is_rejected() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        rejected = client.post(
            "/api/chat",
            headers={"Origin": "https://malicious.example"},
            json={"message": "abre la calculadora", "session_id": "safe-test"},
        )
        accepted = client.post(
            "/api/chat",
            headers={"Origin": "http://127.0.0.1:8765"},
            json={"message": "dime la hora", "session_id": "safe-test"},
        )

    assert rejected.status_code == 403
    assert accepted.status_code == 200


@pytest.mark.parametrize("session_id", ["con espacio", "../escape", "", "x" * 129])
def test_chat_rejects_invalid_session_ids(session_id: str) -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "hola", "session_id": session_id},
        )

    expected = 422 if session_id in {"", "x" * 129} else 400
    assert response.status_code == expected


def test_chat_rejects_empty_and_oversized_messages() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        empty = client.post("/api/chat", json={"message": "", "session_id": "a"})
        whitespace = client.post("/api/chat", json={"message": "   ", "session_id": "a"})
        oversized = client.post(
            "/api/chat",
            json={"message": "x" * 8_001, "session_id": "a"},
        )

    assert empty.status_code == 422
    assert whitespace.status_code == 422
    assert oversized.status_code == 422


def test_conversation_can_be_reset() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        client.post("/api/chat", json={"message": "hola", "session_id": "reset-me"})
        response = client.delete("/api/conversation/reset-me")

    assert response.status_code == 204
    assert "reset-me" not in app.state.conversation._history


def test_reset_rejects_invalid_session_id() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        response = client.delete("/api/conversation/con%20espacio")

    assert response.status_code == 400


def test_empty_and_oversized_audio_are_rejected(tmp_path: Path) -> None:
    app = create_app(fallback_settings(project_root=tmp_path, max_audio_bytes=8))
    with TestClient(app) as client:
        empty = client.post(
            "/api/voice/utterance",
            data={"session_id": "voice"},
            files={"audio": ("empty.wav", b"", "audio/wav")},
        )
        oversized = client.post(
            "/api/voice/utterance",
            data={"session_id": "voice"},
            files={"audio": ("large.wav", b"123456789", "audio/wav")},
        )

    assert empty.status_code == 400
    assert oversized.status_code == 413


def test_voice_pipeline_cleans_temporary_audio(tmp_path: Path) -> None:
    app = create_app(fallback_settings(project_root=tmp_path))
    app.state.transcriber.transcribe = AsyncMock(return_value=("dime la hora", "es"))

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/utterance",
            data={"session_id": "voice", "wake_mode": "false"},
            files={"audio": ("voice.wav", b"not-real-but-mocked", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["provider"] == "safe-command"
    assert list((tmp_path / ".data" / "tmp").iterdir()) == []


def test_voice_wake_mode_ignores_unaddressed_speech(tmp_path: Path) -> None:
    app = create_app(fallback_settings(project_root=tmp_path))
    app.state.transcriber.transcribe = AsyncMock(return_value=("esto no era para ti", "es"))

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/utterance",
            data={"session_id": "voice", "wake_mode": "true"},
            files={"audio": ("voice.wav", b"mock", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["response"] is None


def test_voice_rejects_invalid_session_before_transcription(tmp_path: Path) -> None:
    app = create_app(fallback_settings(project_root=tmp_path))
    app.state.transcriber.transcribe = AsyncMock(return_value=("hola", "es"))

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/utterance",
            data={"session_id": "bad id"},
            files={"audio": ("voice.wav", b"mock", "audio/wav")},
        )

    assert response.status_code == 400
    app.state.transcriber.transcribe.assert_not_awaited()


def test_tts_reports_unavailable_model(tmp_path: Path) -> None:
    app = create_app(fallback_settings(project_root=tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/tts", json={"text": "Hola"})

    assert response.status_code == 503


def test_tts_rejects_whitespace_only_text() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        response = client.post("/api/tts", json={"text": "   "})

    assert response.status_code == 422


def test_websocket_sends_initial_state() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        snapshot = socket.receive_json()

    assert snapshot["state"] == "standby"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("voice.WAV", ".wav"),
        ("voice.webm", ".webm"),
        ("../../payload.exe", ".audio"),
        (None, ".audio"),
    ],
)
def test_audio_suffix_is_allowlisted(filename: str | None, expected: str) -> None:
    assert safe_audio_suffix(filename) == expected


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [("abc-123_test:v1.0", True), ("bad/id", False), ("á", False), ("", False)],
)
def test_session_id_validation(session_id: str, expected: bool) -> None:
    assert valid_session_id(session_id) is expected
