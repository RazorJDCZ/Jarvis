from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from jarvis.actions.models import ExecutionResult
from jarvis.config import Settings
from jarvis.main import create_app, safe_audio_suffix, valid_session_id


def fallback_settings(**overrides: object) -> Settings:
    return Settings(
        brain_mode="fallback",
        safe_actions_enabled=False,
        action_model_planning=False,
        memory_enabled=False,
        **overrides,
    )


def test_health_and_ui_are_available() -> None:
    app = create_app(fallback_settings())
    with TestClient(app) as client:
        health = client.get("/api/health")
        index = client.get("/")
        manifest = client.get("/manifest.webmanifest")
        service_worker = client.get("/service-worker.js")
        stylesheet = client.get("/static/styles.css")
        icon = client.get("/static/icon.svg")
        openapi = client.get("/api/openapi.json")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["brain"]["available"] is True
    assert "actions" in health.json()
    assert "vision" in health.json()
    assert "memory" in health.json()
    assert index.status_code == 200
    assert "JARVIS // Neural Interface" in index.text
    assert 'id="neuralField"' in index.text
    assert 'id="monitorFocus"' in index.text
    assert manifest.status_code == 200
    assert service_worker.status_code == 200
    assert "javascript" in service_worker.headers["content-type"]
    assert "height: clamp(610px" in stylesheet.text
    assert "overflow-y: auto" in stylesheet.text
    assert "scrollbar-gutter: stable" in stylesheet.text
    assert "@media (prefers-reduced-motion: reduce)" in stylesheet.text
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


def test_memory_persists_across_app_restart_and_is_reported_in_health(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        safe_actions_enabled=False,
        action_model_planning=False,
        information_verification_enabled=False,
        memory_enabled=True,
    )
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        remembered = client.post(
            "/api/chat",
            json={
                "message": "Recuerda que mi color favorito es el azul",
                "session_id": "memory-a",
            },
        )
        health = client.get("/api/health")

    second_app = create_app(settings)
    with TestClient(second_app) as client:
        recalled = client.post(
            "/api/chat",
            json={"message": "¿Qué recuerdas de mí?", "session_id": "memory-b"},
        )

    assert remembered.json()["provider"] == "local-memory"
    assert health.json()["memory"]["available"] is True
    assert "1 recuerdo;" in health.json()["memory"]["detail"]
    assert recalled.json()["provider"] == "local-memory"
    assert "color favorito" in recalled.json()["response"]


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


def test_low_risk_action_returns_verified_metadata(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            project_root=tmp_path,
            brain_mode="fallback",
            action_model_planning=False,
        )
    )
    app.state.action_engine.catalog.execute = AsyncMock(
        return_value=ExecutionResult(True, "Calculadora verificada", {"verified": True})
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": "abre la calculadora", "session_id": "action-test"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["provider"] == "action-engine"
    assert payload["action"]["status"] == "completed"
    assert payload["action"]["details"]["verified"] is True


def test_sensitive_action_requires_and_accepts_confirmation(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            project_root=tmp_path,
            brain_mode="fallback",
            action_model_planning=False,
        )
    )
    app.state.action_engine.catalog.execute = AsyncMock(
        return_value=ExecutionResult(True, "Clic verificado")
    )

    with TestClient(app) as client:
        requested = client.post(
            "/api/chat",
            json={"message": "haz clic en Aceptar", "session_id": "action-test"},
        )
        pending = requested.json()["action"]
        decided = client.post(
            "/api/actions/decision",
            json={
                "session_id": "action-test",
                "action_id": pending["action_id"],
                "approve": True,
            },
        )
        audit = client.get("/api/actions/audit?limit=10")

    assert pending["status"] == "pending"
    assert pending["requires_confirmation"] is True
    assert decided.status_code == 200
    assert decided.json()["action"]["status"] == "completed"
    assert len(audit.json()["entries"]) == 2


def test_action_decision_cannot_cross_sessions(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            project_root=tmp_path,
            brain_mode="fallback",
            action_model_planning=False,
        )
    )
    with TestClient(app) as client:
        requested = client.post(
            "/api/chat",
            json={"message": "cierra la ventana de Paint", "session_id": "owner"},
        ).json()
        response = client.post(
            "/api/actions/decision",
            json={
                "session_id": "attacker",
                "action_id": requested["action"]["action_id"],
                "approve": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["action"]["status"] == "rejected"


def test_dialog_choice_endpoint_requires_and_executes_explicit_option(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            project_root=tmp_path,
            brain_mode="fallback",
            action_model_planning=False,
        )
    )
    pending = app.state.action_engine._request_dialog(
        "dialog-owner",
        {
            "parent_handle": 10,
            "dialog_handle": 20,
            "title": "Bloc de notas",
            "message": "¿Quieres guardar los cambios?",
            "options": ["Guardar", "No guardar", "Cancelar"],
        },
    )
    app.state.action_engine.catalog.choose_dialog_option = AsyncMock(
        return_value=ExecutionResult(
            True,
            "Elegí No guardar.",
            {"choice": "No guardar", "verified": True},
        )
    )

    with TestClient(app) as client:
        ambiguous = client.post(
            "/api/actions/decision",
            json={
                "session_id": "dialog-owner",
                "action_id": pending.action_id,
                "approve": True,
            },
        )
        decided = client.post(
            "/api/actions/decision",
            json={
                "session_id": "dialog-owner",
                "action_id": pending.action_id,
                "choice": "No guardar",
            },
        )

    assert ambiguous.json()["action"]["status"] == "pending"
    assert decided.json()["action"]["status"] == "completed"
    assert decided.json()["action"]["details"]["choice"] == "No guardar"


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


@pytest.mark.parametrize(
    ("transcript", "interrupted"),
    [
        ("Jarvis, es suficiente", True),
        ("Jarvis cuéntame algo más", False),
        ("es suficiente", False),
    ],
)
def test_voice_interrupt_endpoint_requires_explicit_addressed_phrase(
    tmp_path: Path,
    transcript: str,
    interrupted: bool,
) -> None:
    app = create_app(fallback_settings(project_root=tmp_path))
    app.state.transcriber.transcribe = AsyncMock(return_value=(transcript, "es"))

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/interrupt",
            data={"session_id": "voice"},
            files={"audio": ("interrupt.wav", b"mock", "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["interrupted"] is interrupted
    assert list((tmp_path / ".data" / "tmp").iterdir()) == []


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
