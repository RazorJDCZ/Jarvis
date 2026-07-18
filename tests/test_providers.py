from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jarvis.config import Settings
from jarvis.providers.brain import AutoBrain, FallbackBrain, OllamaBrain, build_brain
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS


def mock_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr("jarvis.providers.brain.httpx.AsyncClient", client_factory)


@pytest.mark.asyncio
async def test_ollama_status_finds_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})

    mock_httpx(monkeypatch, handler)
    status = await OllamaBrain(Settings()).status()

    assert status.available is True
    assert "qwen3.5:4b" in status.name


@pytest.mark.asyncio
async def test_ollama_status_handles_malformed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [None, {"wrong": 1}]})

    mock_httpx(monkeypatch, handler)
    status = await OllamaBrain(Settings()).status()

    assert status.available is False
    assert "falta descargar" in status.detail


@pytest.mark.asyncio
async def test_ollama_status_handles_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    mock_httpx(monkeypatch, handler)
    status = await OllamaBrain(Settings()).status()

    assert status.available is False
    assert "no detectado" in status.detail


@pytest.mark.asyncio
async def test_ollama_chat_sends_non_streaming_request(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "  Todo listo.  "}})

    mock_httpx(monkeypatch, handler)
    answer = await OllamaBrain(Settings()).chat([{"role": "user", "content": "hola"}])

    assert answer == "Todo listo."
    assert received[0]["stream"] is False
    assert received[0]["think"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"message": None}, {"message": {"content": "  "}}],
)
async def test_ollama_chat_rejects_empty_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    mock_httpx(monkeypatch, handler)

    with pytest.raises(RuntimeError, match="respuesta vacia"):
        await OllamaBrain(Settings()).chat([{"role": "user", "content": "hola"}])


@pytest.mark.asyncio
async def test_fallback_brain_has_useful_offline_responses() -> None:
    brain = FallbackBrain()

    greeting = await brain.chat([{"role": "user", "content": "Hola"}])
    identity = await brain.chat([{"role": "user", "content": "¿Quién eres?"}])
    generic = await brain.chat([{"role": "user", "content": "Prueba"}])

    assert "Juandi" in greeting
    assert "asistente local" in identity
    assert "Prueba" in generic


def test_brain_factory_respects_mode() -> None:
    assert isinstance(build_brain(Settings(brain_mode="fallback")), FallbackBrain)
    assert isinstance(build_brain(Settings(brain_mode="ollama")), OllamaBrain)
    assert isinstance(build_brain(Settings(brain_mode="auto")), AutoBrain)


@pytest.mark.asyncio
async def test_voice_provider_statuses_without_models(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path, stt_model="missing")

    stt = await WhisperTranscriber(settings).status()
    tts = await PiperTTS(settings).status()

    assert stt.available is True
    assert "primera frase" in stt.detail
    assert tts.available is False
    assert "Windows" in tts.detail
