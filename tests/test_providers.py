from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from jarvis.config import Settings
from jarvis.providers.brain import AutoBrain, FallbackBrain, OllamaBrain, build_brain
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS
from jarvis.schemas import ProviderStatus


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
    assert len(received) == 1
    assert received[0]["stream"] is False
    assert received[0]["think"] is False
    assert received[0]["keep_alive"] == "0s"
    assert received[0]["options"]["temperature"] == pytest.approx(0.45)
    assert received[0]["options"]["num_predict"] == 512


@pytest.mark.asyncio
async def test_ollama_deep_chat_uses_a_larger_controlled_answer_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "thinking": "razonamiento privado",
                    "content": "Conclusión analítica.",
                }
            },
        )

    mock_httpx(monkeypatch, handler)
    answer = await OllamaBrain(Settings()).chat_deep([{"role": "user", "content": "analiza esto"}])

    assert answer == "Conclusión analítica."
    assert received[0]["think"] is False
    assert received[0]["options"]["temperature"] == pytest.approx(0.35)
    assert received[0]["options"]["num_predict"] == 1_024


@pytest.mark.asyncio
async def test_ollama_warmup_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"response": "LISTO"})

    mock_httpx(monkeypatch, handler)
    brain = OllamaBrain(
        Settings(
            ollama_warmup_enabled=True,
            ollama_warmup_min_free_gb=0,
            ollama_keep_alive="30m",
        )
    )

    assert await brain.warmup() is True
    assert await brain.warmup() is True
    assert requests == ["/api/generate"]


@pytest.mark.asyncio
async def test_ollama_warmup_skips_when_memory_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("No debe contactar Ollama con memoria insuficiente")

    mock_httpx(monkeypatch, handler)
    brain = OllamaBrain(Settings(ollama_warmup_enabled=True, ollama_warmup_min_free_gb=6))
    monkeypatch.setattr(brain, "_available_memory_gb", lambda: 1.5)

    assert await brain.warmup() is False


@pytest.mark.asyncio
async def test_ollama_release_only_unloads_a_resident_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        return httpx.Response(200, json={"done": True})

    mock_httpx(monkeypatch, handler)
    brain = OllamaBrain(Settings())

    assert await brain.release() is True
    assert requests == [
        ("GET", "/api/ps", None),
        ("POST", "/api/generate", {"model": "qwen3.5:4b", "keep_alive": 0}),
    ]


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

    assert "Juan Diego" in greeting
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


@pytest.mark.asyncio
async def test_kokoro_is_preferred_and_generates_pcm_wav(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        kokoro_voice="em_alex",
        kokoro_speed=0.96,
    )
    provider = PiperTTS(settings)

    class FakeKokoro:
        voices = ("em_alex", "em_santa")
        invocation = None

        def create(self, text, voice, speed, lang):
            self.invocation = (text, voice, speed, lang)
            return np.zeros(2_400, dtype=np.float32), 24_000

    fake_kokoro = FakeKokoro()
    provider._kokoro = fake_kokoro

    status = await provider.status()
    audio = await provider.synthesize("Hola, Juandi.")

    assert status.available is True
    assert "Kokoro" in status.name
    assert audio.startswith(b"RIFF")
    assert fake_kokoro.invocation == ("Hola, Juandi.", "em_alex", 0.96, "es")


@pytest.mark.asyncio
async def test_kokoro_failure_disables_it_and_falls_back_to_piper(tmp_path: Path) -> None:
    provider = PiperTTS(Settings(project_root=tmp_path))

    class BrokenKokoro:
        voices = ("em_alex",)

        @staticmethod
        def create(*_args, **_kwargs):
            raise ValueError("broken model")

    class FakePiper:
        @staticmethod
        def synthesize_wav(_text, wav_file, syn_config=None) -> None:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22_050)
            wav_file.writeframes(b"\x00\x00" * 10)

    provider._kokoro = BrokenKokoro()
    provider._voice = FakePiper()

    audio = await provider.synthesize("Hola.")
    status = await provider.status()

    assert audio.startswith(b"RIFF")
    assert provider._kokoro_failed is True
    assert "Piper" in status.name


@pytest.mark.asyncio
async def test_piper_uses_gentle_configured_voice_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        project_root=tmp_path,
        piper_speaker_id=0,
        piper_length_scale=1.06,
        piper_noise_scale=0.60,
        piper_noise_w_scale=0.70,
        piper_volume=0.96,
    )
    provider = PiperTTS(settings)

    class FakeVoice:
        config = None

        def synthesize_wav(self, _text, wav_file, syn_config=None) -> None:
            self.config = syn_config
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22_050)
            wav_file.writeframes(b"\x00\x00" * 10)

    fake_voice = FakeVoice()
    provider._voice = fake_voice

    async def available() -> ProviderStatus:
        return ProviderStatus(available=True, name="Piper", detail="ok")

    monkeypatch.setattr(provider, "status", available)

    audio = await provider.synthesize("Hola, Juandi.")

    assert audio.startswith(b"RIFF")
    assert fake_voice.config.speaker_id == 0
    assert fake_voice.config.length_scale == pytest.approx(1.06)
    assert fake_voice.config.noise_scale == pytest.approx(0.60)
    assert fake_voice.config.noise_w_scale == pytest.approx(0.70)
    assert fake_voice.config.volume == pytest.approx(0.96)
