from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.capabilities.suite import CapabilitySuite
from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.services.automations import AutomationStore
from jarvis.services.memory import MemoryCandidate, MemoryStore
from jarvis.services.weather import FORECAST_URL, GEOCODING_URL, WeatherService


def test_automation_rules_are_safe_configurable_and_deduplicated(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.sqlite3")
    rules = {rule.rule_id: rule for rule in store.list()}

    assert rules["morning-briefing"].enabled is True
    assert rules["important-mail"].enabled is False
    updated = store.save(
        rule_id="calendar-soon",
        name=rules["calendar-soon"].name,
        kind="calendar_soon",
        enabled=True,
        hour=8,
        lead_minutes=45,
    )
    assert updated.enabled is True and updated.lead_minutes == 45
    assert store.claim(updated.rule_id, "phone", "event:date") is True
    assert store.claim(updated.rule_id, "phone", "event:date") is False
    assert store.delete("calendar-soon") is False


def test_automation_notification_queue_is_deduplicated_and_persistent(tmp_path) -> None:
    store = AutomationStore(tmp_path / "automations.sqlite3")
    payload = {"event": "automation", "title": "Revisar agenda"}

    assert store.enqueue_notification("phone", "agenda:1", payload, max_attempts=1)
    assert not store.enqueue_notification("phone", "agenda:1", payload)
    job = store.due_jobs()[0]
    assert job.payload == payload and job.attempts == 1
    assert store.finish_job(job.job_id, error="offline")
    assert store.job_stats()["failed"] == 1

    restarted = AutomationStore(store.path)
    assert restarted.job_stats()["failed"] == 1


@pytest.mark.asyncio
async def test_weather_service_uses_profile_location_and_cache(tmp_path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"location": "Quito, Ecuador"}), encoding="utf-8")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).startswith(GEOCODING_URL):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Quito",
                            "admin1": "Pichincha",
                            "country": "Ecuador",
                            "latitude": -0.22,
                            "longitude": -78.51,
                        }
                    ]
                },
            )
        assert str(request.url).startswith(FORECAST_URL)
        return httpx.Response(
            200,
            json={
                "timezone": "America/Guayaquil",
                "current": {
                    "temperature_2m": 18.4,
                    "apparent_temperature": 18.0,
                    "precipitation": 0,
                    "weather_code": 2,
                    "wind_speed_10m": 7.2,
                },
                "daily": {
                    "temperature_2m_min": [10.0, 11.0],
                    "temperature_2m_max": [20.0, 21.0],
                    "precipitation_probability_max": [35, 40],
                    "weather_code": [2, 61],
                },
            },
        )

    service = WeatherService(profile, transport=httpx.MockTransport(handler))
    first = await service.current()
    second = await service.current()

    assert first["location"] == "Quito, Pichincha, Ecuador"
    assert first["temperature_c"] == 18.4 and "35 por ciento" in first["summary"]
    assert second["cached"] is True
    assert len(calls) == 2


def test_personal_memory_and_automation_api_roundtrip(tmp_path) -> None:
    config = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        voice_preload=False,
        adaptive_resources=False,
        semantic_enabled=False,
        appa_auto_discover=False,
        action_model_planning=False,
    )
    app = create_app(config)
    with TestClient(app) as client:
        rules = client.get("/api/assistant/automations")
        assert rules.status_code == 200 and len(rules.json()["rules"]) == 5
        rule = next(
            item for item in rules.json()["rules"] if item["rule_id"] == "calendar-soon"
        )
        changed = client.put(
            "/api/assistant/automations/calendar-soon",
            json={
                "name": rule["name"],
                "kind": rule["kind"],
                "enabled": True,
                "hour": 9,
                "lead_minutes": 60,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["rule"]["lead_minutes"] == 60

        created = client.post(
            "/api/assistant/memory/entities",
            json={
                "kind": "rutina",
                "name": "Gimnasio",
                "relation": "bienestar",
                "details": "Tres veces por semana",
            },
        )
        assert created.status_code == 200
        memory = client.get("/api/assistant/memory").json()
        assert memory["entities"][0]["name"] == "Gimnasio"
        security = client.get("/api/assistant/security")
        assert security.status_code == 200
        assert security.json()["file_search"]["read_only"] is True


@pytest.mark.asyncio
async def test_personal_search_fans_out_and_keeps_results_read_only(tmp_path) -> None:
    config = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        voice_preload=False,
        semantic_enabled=False,
        appa_auto_discover=False,
        action_model_planning=False,
    )
    suite = CapabilitySuite(config)
    await suite.connectors.local.create_task("owner", "Preparar proyecto Atlas")
    memory_store = MemoryStore(tmp_path / "personal-memory.sqlite3")
    memory_store.upsert(MemoryCandidate("atlas", "Atlas es el proyecto final.", "proyecto"))
    suite.knowledge = SimpleNamespace(
        search=lambda *_args: [
            SimpleNamespace(
                title="Notas Atlas", excerpt="Arquitectura del proyecto", source_id="doc1"
            )
        ]
    )
    suite.file_search = SimpleNamespace(
        search=lambda *_args, **_kwargs: {
            "items": [{"name": "atlas.md", "path": str(tmp_path / "atlas.md")}]
        }
    )
    suite.personal_search.attach(
        mail=SimpleNamespace(
            search=lambda *_args: {
                "items": [
                    {
                        "id": "mail1",
                        "subject": "Proyecto Atlas",
                        "sender": "Docente",
                        "summary": "Entrega final",
                        "relevance": 20,
                    }
                ]
            }
        ),
        organizer=SimpleNamespace(
            calendar_events=lambda: {
                "events": [{"id": "event1", "title": "Reunion Atlas"}]
            }
        ),
        memory=SimpleNamespace(store=memory_store),
    )

    result = await suite.personal_search.search("owner", "Atlas")

    assert result["read_only"] is True
    assert {item["source"] for item in result["items"]} == {
        "correo",
        "calendario",
        "appa",
        "memoria",
        "biblioteca",
        "archivo",
    }
