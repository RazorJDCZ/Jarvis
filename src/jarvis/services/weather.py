from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "cielo despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "niebla",
    48: "niebla con escarcha",
    51: "llovizna ligera",
    53: "llovizna",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia",
    65: "lluvia intensa",
    71: "nieve ligera",
    73: "nieve",
    75: "nieve intensa",
    80: "chubascos ligeros",
    81: "chubascos",
    82: "chubascos intensos",
    95: "tormenta",
    96: "tormenta con granizo",
    99: "tormenta fuerte con granizo",
}


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in text if not unicodedata.combining(char)).split()
    )


class WeatherService:
    """Bounded, keyless weather lookup with a small local cache."""

    def __init__(
        self,
        profile_path: Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_seconds: int = 600,
    ) -> None:
        self.profile_path = profile_path
        self.transport = transport
        self.cache_seconds = max(60, min(cache_seconds, 3_600))
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def default_location(self) -> str:
        try:
            payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
            location = payload.get("location", "") if isinstance(payload, dict) else ""
            if isinstance(location, str) and location.strip():
                return " ".join(location.split())[:160]
        except (OSError, ValueError):
            pass
        return "Quito, Ecuador"

    async def current(self, location: str = "") -> dict[str, Any]:
        query = " ".join((location or self.default_location()).split()).strip()[:160]
        if len(query) < 2:
            raise ValueError("Indica una ubicación válida")
        cache_key = _normalized(query)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.cache_seconds:
            return {**cached[1], "cached": True}

        async with httpx.AsyncClient(
            timeout=10,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            geocoding = await client.get(
                GEOCODING_URL,
                params={"name": query, "count": 1, "language": "es", "format": "json"},
            )
            geocoding.raise_for_status()
            candidates = geocoding.json().get("results", [])
            if not candidates:
                raise ValueError("No encontré esa ubicación")
            place = candidates[0]
            latitude = float(place["latitude"])
            longitude = float(place["longitude"])
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("El proveedor devolvió coordenadas no válidas")
            forecast = await client.get(
                FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,apparent_temperature,precipitation,"
                        "weather_code,wind_speed_10m"
                    ),
                    "daily": (
                        "temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max,weather_code"
                    ),
                    "timezone": "auto",
                    "forecast_days": 2,
                },
            )
            forecast.raise_for_status()
            data = forecast.json()

        current = data.get("current", {})
        daily = data.get("daily", {})
        code = int(current.get("weather_code", -1))
        name_parts = [str(place.get("name", query))]
        if place.get("admin1") and place.get("admin1") != place.get("name"):
            name_parts.append(str(place["admin1"]))
        if place.get("country"):
            name_parts.append(str(place["country"]))
        result = {
            "location": ", ".join(name_parts),
            "latitude": latitude,
            "longitude": longitude,
            "timezone": str(data.get("timezone", "")),
            "condition": WEATHER_CODES.get(code, "condiciones variables"),
            "temperature_c": round(float(current.get("temperature_2m", 0)), 1),
            "feels_like_c": round(float(current.get("apparent_temperature", 0)), 1),
            "precipitation_mm": round(float(current.get("precipitation", 0)), 1),
            "wind_kmh": round(float(current.get("wind_speed_10m", 0)), 1),
            "today_min_c": round(float((daily.get("temperature_2m_min") or [0])[0]), 1),
            "today_max_c": round(float((daily.get("temperature_2m_max") or [0])[0]), 1),
            "rain_probability": int(
                float((daily.get("precipitation_probability_max") or [0])[0])
            ),
            "source": "Open-Meteo",
            "cached": False,
        }
        result["summary"] = (
            f"En {result['location']} hay {result['condition']} y "
            f"{result['temperature_c']} grados; se sienten como {result['feels_like_c']}. "
            f"Para hoy se esperan entre {result['today_min_c']} y {result['today_max_c']} grados, "
            f"con {result['rain_probability']} por ciento de probabilidad de lluvia."
        )
        self._cache[cache_key] = (time.monotonic(), result)
        return result
