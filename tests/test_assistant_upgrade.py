from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.capabilities.semantic import SemanticKnowledgeStore
from jarvis.capabilities.suite import CapabilitySuite
from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.schemas import ChatResponse
from jarvis.services.memory import MemoryCandidate, MemoryStore
from jarvis.services.notifications import NotificationStore
from jarvis.services.performance import (
    PerformanceLog,
    model_keep_alive,
    response_events,
    token_sink,
)
from jarvis.services.preferences import Preferences, PreferenceStore
from jarvis.state import StateHub


def settings(tmp_path, **kwargs):
    return Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        safe_actions_enabled=False,
        action_model_planning=False,
        appa_auto_discover=False,
        voice_preload=False,
        **kwargs,
    )


def test_notification_survives_restart_and_requires_correct_session_ack(tmp_path):
    store = NotificationStore(tmp_path / "notifications.db")
    event = store.publish("phone", {"event": "reminder", "id": "r1", "due_at": "today"})
    store.publish("phone", {"event": "reminder", "id": "r1", "due_at": "today"})
    restarted = NotificationStore(store.path)
    assert len(restarted.pending("phone")) == 1
    assert restarted.pending("other") == []
    restarted.acknowledge("other", [event["notification_id"]])
    assert len(restarted.pending("phone")) == 1
    restarted.acknowledge("phone", [event["notification_id"]])
    restarted.publish("phone", {"event": "reminder", "id": "r1", "due_at": "today"})
    assert restarted.pending("phone") == []


@pytest.mark.asyncio
async def test_slow_websocket_never_blocks_commands():
    hub = StateHub()
    socket = AsyncMock()
    socket.send_json.side_effect = lambda payload: asyncio.sleep(5)

    # AsyncMock side effects need an async function to actually await the delay.
    async def slow(payload):
        await asyncio.sleep(5)

    socket.send_json.side_effect = slow
    hub._clients.add(socket)
    start = time.perf_counter()
    await hub.set("thinking", "test")
    assert time.perf_counter() - start < 0.1
    await asyncio.sleep(0.6)
    assert socket not in hub._clients
    await hub.close()


@pytest.mark.asyncio
async def test_stream_emits_text_before_completion_and_records_timing():
    release = asyncio.Event()

    async def operation():
        await token_sink.get()("Primera frase.")
        await release.wait()
        return ChatResponse(response="Primera frase. Segunda.", provider="test")

    log = PerformanceLog()
    events = response_events(operation, log, "phone")
    assert json.loads(await anext(events))["event"] == "accepted"
    assert json.loads(await anext(events))["text"] == "Primera frase."
    release.set()
    assert json.loads(await anext(events))["event"] == "done"
    await events.aclose()
    assert "first_text" in log.recent("phone")[0]["timings_ms"]
    assert not log.recent("other")


@pytest.mark.asyncio
async def test_stream_never_emits_model_emojis():
    async def operation():
        await token_sink.get()("Listo 😏.")
        return ChatResponse(response="Listo.", provider="test")

    events = response_events(operation, PerformanceLog(), "phone")
    await anext(events)
    token = json.loads(await anext(events))
    done = json.loads(await anext(events))
    await events.aclose()

    assert token == {"event": "token", "text": "Listo."}
    assert done["response"] == "Listo."


@pytest.mark.asyncio
async def test_stream_disconnect_cancels_inference():
    cancelled = asyncio.Event()

    async def operation():
        try:
            await token_sink.get()("Hola")
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    events = response_events(operation, PerformanceLog(), "phone")
    await anext(events)
    await anext(events)
    await events.aclose()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_stream_timeout_cancels_inference_and_allows_a_retry():
    cancelled = asyncio.Event()

    async def operation():
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    events = response_events(operation, PerformanceLog(), "voice", timeout=0.01)
    assert json.loads(await anext(events))["event"] == "accepted"
    error = json.loads(await anext(events))
    await events.aclose()

    assert error["event"] == "error"
    assert "puedes hablar de nuevo" in error["detail"]
    assert cancelled.is_set()


def test_voice_client_has_stream_and_playback_watchdogs():
    root = Path(__file__).resolve().parents[1]
    assistant = (root / "src" / "jarvis" / "web" / "assistant.js").read_text(
        encoding="utf-8"
    )
    app = (root / "src" / "jarvis" / "web" / "app.js").read_text(encoding="utf-8")

    assert "VOICE_STREAM_TIMEOUT_MS" in assistant
    assert "controller.abort()" in assistant
    assert "speechWatchdog" in app
    assert "TTS_REQUEST_TIMEOUT_MS" in app


def test_memory_edit_rejects_stale_version_and_deletes_exact_key(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    entry = store.upsert(MemoryCandidate("color", "Prefiere azul", "preference"))
    assert store.edit_entry(entry.memory_key, "Prefiere verde", entry.updated_at)
    assert not store.edit_entry(entry.memory_key, None, entry.updated_at)
    updated = store.list_entries()[0]
    assert updated.content == "Prefiere verde"
    assert store.edit_entry(updated.memory_key, None, updated.updated_at)
    assert not store.list_entries()


def test_memory_retrieves_entries_beyond_old_hundred_entry_limit(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    for i in range(120):
        store.upsert(MemoryCandidate(str(i), f"Proyecto número {i}", "project"))
    assert len(store.list_entries(500)) == 120


def test_adaptive_residency_obeys_ram_and_explicit_disabled_setting(tmp_path, monkeypatch):
    from jarvis.services import performance

    config = settings(tmp_path, adaptive_resources=True)
    monkeypatch.setattr(performance, "available_ram_gb", lambda: 1)
    assert model_keep_alive(config, "9m") == "0s"
    monkeypatch.setattr(performance, "available_ram_gb", lambda: 5)
    assert model_keep_alive(config, "0s") == "3m"
    assert model_keep_alive(replace(config, adaptive_resources=False), "9m") == "9m"


def test_semantic_retrieval_matches_paraphrase_and_isolates_sessions(tmp_path, monkeypatch):
    store = SemanticKnowledgeStore(
        tmp_path / "knowledge.db", settings(tmp_path, semantic_enabled=True)
    )
    monkeypatch.setattr(store, "_embed", lambda texts: [[1.0, 0.0] for _ in texts])
    source = store.upsert_source(
        "a", "Apunte", "[Página 2]\nEl automóvil requiere combustible.", "test"
    )
    result = store.search("a", "vehículo gasolina")
    assert result[0].source_id == source.source_id
    assert "Página 2" in result[0].excerpt
    assert "fragmento 1" in result[0].citation
    assert not store.search("b", "vehículo gasolina")


def test_semantic_outage_preserves_lexical_search(tmp_path, monkeypatch):
    store = SemanticKnowledgeStore(
        tmp_path / "knowledge.db", settings(tmp_path, semantic_enabled=True)
    )

    def fail(texts):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(store, "_embed", fail)
    store.upsert_source("a", "Apunte", "Fotosíntesis usa luz solar", "test")
    assert store.search("a", "fotosíntesis")
    assert store.last_error


def test_semantic_refuses_nonlocal_processing(tmp_path):
    store = SemanticKnowledgeStore(
        tmp_path / "knowledge.db", settings(tmp_path, ollama_url="https://example.com")
    )
    with pytest.raises(ValueError, match="local"):
        store._embed(["private document"])


def test_api_stream_memory_preferences_and_origin_validation(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream", json={"message": "dime la hora", "session_id": "phone"}
        )
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["event"] == "accepted"
        assert events[-1]["event"] == "done"
        assert events[-1]["response"]
        assert client.get("/api/performance?session_id=phone").json()["requests"]
        assert not client.get("/api/performance?session_id=other").json()["requests"]
        assert client.get("/api/assistant/memory").status_code == 200
        assert client.put("/api/assistant/preferences", json={"voice_speed": 10}).status_code == 422
        assert (
            client.put("/api/assistant/preferences", json={"performance": "economy"}).status_code
            == 200
        )
        assert client.get("/api/assistant/preferences").json()["performance"] == "economy"
        assert client.patch("/api/assistant/profile", json={"location": "Quito"}).status_code == 200
        assert client.get("/api/assistant/memory").json()["profile"]["location"] == "Quito"
        assert (
            client.post(
                "/api/chat/stream",
                headers={"Origin": "https://evil.example"},
                json={"message": "hola"},
            ).status_code
            == 403
        )


def test_voice_stream_uses_same_transcription_and_gate(tmp_path):
    app = create_app(settings(tmp_path))
    app.state.transcriber.transcribe = AsyncMock(return_value=("Jarvis dime la hora", "es"))
    with TestClient(app) as client:
        response = client.post(
            "/api/voice/stream",
            data={"session_id": "phone", "wake_mode": "true"},
            files={"audio": ("test.wav", b"test", "audio/wav")},
        )
        event = json.loads(response.text.splitlines()[-1])
        assert event["accepted"]
        assert event["transcript"] == "Jarvis dime la hora"
        assert "transcription" in event["timings_ms"]


def test_quiet_hours_cross_midnight(tmp_path):
    store = PreferenceStore(tmp_path / "prefs.json")
    store.save(Preferences(quiet_start=22, quiet_end=7))
    assert store.quiet(23) and store.quiet(6)
    assert not store.quiet(12)


@pytest.mark.asyncio
async def test_proactive_briefing_is_once_per_day_even_after_restart(tmp_path):
    config = settings(tmp_path)
    suite = CapabilitySuite(config)
    suite.preferences.save(Preferences(proactive=True, briefing_hour=0, quiet_start=0, quiet_end=0))
    suite.outbox.register("phone")
    suite.briefing = AsyncMock(return_value={"summary": "Tareas de hoy"})
    await suite._proactive_tick()
    await suite._proactive_tick()
    assert len(suite.outbox.pending("phone")) == 1
    again = CapabilitySuite(config)
    again.briefing = AsyncMock(return_value={"summary": "Duplicado"})
    await again._proactive_tick()
    again.briefing.assert_not_called()
    assert suite.outbox.has_event("phone", "briefing:" + datetime.now().date().isoformat())
    await suite.close()
    await again.close()


@pytest.mark.asyncio
async def test_adaptive_transcription_parks_gpu_and_falls_back_during_inference(
    tmp_path, monkeypatch
):
    from jarvis.providers import stt as module

    class FakeModel:
        def __init__(self):
            self.loaded = 0
            self.parked = 0
            self.model = self

        def load_model(self):
            self.loaded += 1

        def unload_model(self, to_cpu):
            assert to_cpu
            self.parked += 1

        def transcribe(self, path, **kwargs):
            return [SimpleNamespace(text="Dime la hora")], SimpleNamespace(language="es")

    transcriber = module.WhisperTranscriber(settings(tmp_path, stt_device="auto"))
    transcriber._model = FakeModel()
    transcriber._cpu_model = FakeModel()
    transcriber._device = "cuda"
    monkeypatch.setattr(module, "gpu_free_mb", lambda: 3000)
    monkeypatch.setattr(module, "OLLAMA_RUNTIME_LOCK", SimpleNamespace(locked=lambda: False))
    assert (await transcriber.transcribe(tmp_path / "fake.wav"))[0] == "Dime la hora"
    assert transcriber._model.loaded == 1 and transcriber._model.parked == 1
    assert transcriber.last_device == "cuda"
    monkeypatch.setattr(module, "OLLAMA_RUNTIME_LOCK", SimpleNamespace(locked=lambda: True))
    await transcriber.transcribe(tmp_path / "fake.wav")
    assert transcriber._model.loaded == 1
    assert transcriber.last_device == "cpu"


@pytest.mark.asyncio
async def test_system_alert_is_acknowledged_without_repeating(tmp_path):
    suite = CapabilitySuite(settings(tmp_path))
    suite.notifications("phone")
    await suite._notify("system", {"event": "system-alert", "message": "RAM alta"})
    pending = suite.notifications("phone")
    assert len(pending) == 1
    assert len(suite.notifications("phone")) == 1
    suite.outbox.acknowledge("phone", [pending[0]["notification_id"]])
    assert not suite.notifications("phone")
    await suite.close()


def test_eval_all_includes_every_fixture():
    from scripts.evaluate_agent import FIXTURES, load_cases

    assert len(load_cases("all", 0)) == sum(len(load_cases(name, 0)) for name in FIXTURES)


@pytest.mark.parametrize(
    "text",
    [
        "Cuéntame una historia breve sobre un robot cocinero.",
        "Inventa un cuento sobre una ventana mágica.",
        "Escribe un poema sobre el mar.",
        "Jarvis, cuéntame otra historia.",
    ],
)
def test_creative_conversation_skips_action_planning(text):
    from jarvis.actions.parser import DeterministicActionParser

    parser = DeterministicActionParser()
    assert parser.is_explicitly_non_action(text)
    assert not parser.has_agent_intent(text)


def test_creative_request_with_explicit_desktop_destination_can_use_tools():
    from jarvis.actions.parser import DeterministicActionParser

    assert not DeterministicActionParser().is_explicitly_non_action(
        "Escribe un poema en el bloc de notas"
    )
