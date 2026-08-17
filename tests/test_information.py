from __future__ import annotations

import httpx
import pytest

from jarvis.config import Settings
from jarvis.services.information import InformationVerifier


def weather_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Vancouver",
                            "country": "Canada",
                            "latitude": 49.25,
                            "longitude": -123.12,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-07-21T14:30",
                    "temperature_2m": 18.4,
                    "apparent_temperature": 17.9,
                    "relative_humidity_2m": 66,
                    "precipitation": 0,
                    "weather_code": 2,
                    "wind_speed_10m": 8.1,
                },
                "daily": {
                    "time": ["2026-07-21", "2026-07-22", "2026-07-23"],
                    "weather_code": [2, 61, 3],
                    "temperature_2m_max": [20, 17.5, 18],
                    "temperature_2m_min": [12, 11.2, 10],
                    "precipitation_probability_max": [10, 75, 20],
                },
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_current_weather_is_answered_directly_from_open_meteo() -> None:
    verifier = InformationVerifier(Settings(), transport=weather_transport())

    result = await verifier.verify("¿Qué temperatura hace en Vancouver?")

    assert result is not None
    assert result.direct_answer is not None
    assert "18.4" in result.direct_answer
    assert "Vancouver, Canada" in result.direct_answer
    assert "Open-Meteo" in result.direct_answer
    assert result.sources == ("Open-Meteo",)


@pytest.mark.asyncio
async def test_tomorrow_weather_uses_daily_forecast() -> None:
    verifier = InformationVerifier(Settings(), transport=weather_transport())

    result = await verifier.verify("¿Cómo estará el clima mañana en Vancouver?")

    assert result is not None
    assert result.direct_answer is not None
    assert "2026-07-22" in result.direct_answer
    assert "17.5" in result.direct_answer
    assert "75" in result.direct_answer


@pytest.mark.asyncio
async def test_general_fact_injects_wikipedia_evidence() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "title": "Ecuador",
                            "extract": "Ecuador es un pais de America del Sur.",
                            "fullurl": "https://es.wikipedia.org/wiki/Ecuador",
                        }
                    ]
                }
            },
        )

    verifier = InformationVerifier(Settings(), transport=httpx.MockTransport(handler))
    result = await verifier.verify("¿Dónde está Ecuador?")

    assert result is not None
    assert result.direct_answer is None
    assert "Ecuador es un pais" in result.evidence
    assert result.sources == ("https://es.wikipedia.org/wiki/Ecuador",)


@pytest.mark.asyncio
async def test_personal_question_does_not_leave_the_local_profile() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    verifier = InformationVerifier(Settings(), transport=httpx.MockTransport(handler))

    result = await verifier.verify("¿Cómo se llama mi novia?")

    assert result is None
    assert called is False


@pytest.mark.asyncio
async def test_source_failure_returns_honest_answer_instead_of_guessing() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(503))
    verifier = InformationVerifier(Settings(), transport=transport)

    weather = await verifier.verify("temperatura en Quito")
    fact = await verifier.verify("¿Quién es el presidente de Ecuador?")

    assert weather is not None and "no inventar" in (weather.direct_answer or "")
    assert fact is not None and "no inventar" in (fact.direct_answer or "")


@pytest.mark.asyncio
async def test_nonfactual_conversation_does_not_make_network_request() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    verifier = InformationVerifier(Settings(), transport=httpx.MockTransport(handler))

    result = await verifier.verify("¿Cómo estás hoy?")

    assert result is None
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    (
        "Hola Jarvis, preséntate brevemente y confirma que la prueba funciona",
        "Estoy contento de que el proyecto esté avanzando",
        "Cuéntame de ti",
    ),
)
async def test_embedded_que_and_personal_presentation_do_not_trigger_public_lookup(
    message: str,
) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    verifier = InformationVerifier(Settings(), transport=httpx.MockTransport(handler))

    assert await verifier.verify(message) is None
    assert called is False
