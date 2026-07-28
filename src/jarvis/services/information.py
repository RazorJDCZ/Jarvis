from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx

from jarvis.config import Settings


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    direct_answer: str | None = None
    evidence: str = ""
    sources: tuple[str, ...] = ()


class InformationVerifier:
    _GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    _WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
    _WIKIPEDIA_URL = "https://es.wikipedia.org/w/api.php"
    _PERSONAL_MARKERS = (
        "mi novia",
        "sobre mi",
        "quien soy",
        "que sabes de mi",
        "mis gustos",
        "mi cumpleanos",
        "mi fecha de nacimiento",
        "donde vivo",
        "que estudio",
        "cuantos anos tengo",
        "que edad tengo",
        "nahir",
        "quien eres",
        "tu nombre",
        "sobre ti",
    )
    _CONVERSATIONAL_MARKERS = (
        "como estas",
        "como te sientes",
        "que tal",
        "que opinas",
        "que piensas",
        "puedes ayudarme",
        "me cuentas un chiste",
    )
    _QUESTION_MARKERS = (
        "que ",
        "quien ",
        "cual ",
        "donde ",
        "cuando ",
        "por que ",
        "como ",
        "cuanto ",
        "dime quien",
        "dime que",
        "explicame ",
        "informacion sobre ",
    )
    _UNSUPPORTED_LIVE_MARKERS = (
        "ultimas noticias",
        "noticias de hoy",
        "precio actual",
        "cotizacion",
        "tipo de cambio",
        "marcador actual",
        "resultado del partido",
        "trafico actual",
    )
    _WEATHER_MARKERS = (
        "temperatura",
        "clima",
        "tiempo hace",
        "pronostico",
        "va a llover",
        "esta lloviendo",
    )
    _WEATHER_CODES = {
        0: "cielo despejado",
        1: "mayormente despejado",
        2: "parcialmente nublado",
        3: "nublado",
        45: "niebla",
        48: "niebla con escarcha",
        51: "llovizna ligera",
        53: "llovizna moderada",
        55: "llovizna intensa",
        61: "lluvia ligera",
        63: "lluvia moderada",
        65: "lluvia intensa",
        71: "nieve ligera",
        73: "nieve moderada",
        75: "nieve intensa",
        80: "chubascos ligeros",
        81: "chubascos moderados",
        82: "chubascos intensos",
        95: "tormenta",
        96: "tormenta con granizo",
        99: "tormenta fuerte con granizo",
    }

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.enabled = settings.information_verification_enabled
        self.timeout = max(1.0, min(settings.information_timeout, 30.0))
        self.default_location = "Quito, Ecuador"
        self._transport = transport

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "User-Agent": "JarvisLocal/0.2 (https://github.com/RazorJDCZ/Jarvis)"
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            transport=self._transport,
            headers=headers,
            follow_redirects=False,
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("la fuente no devolvio un objeto JSON")
        return payload

    @classmethod
    def _weather_location(cls, message: str) -> str:
        cleaned = re.sub(r"[?!.]+$", "", message.strip())
        match = re.search(r"\b(?:en|para)\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if match is None:
            match = re.search(r"\bde\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if match is None:
            return ""
        location = re.sub(
            r"\b(?:hoy|ahora|actualmente|manana|mañana)$",
            "",
            match.group(1).strip(),
            flags=re.IGNORECASE,
        ).strip(" ,")
        return location[:120]

    async def _weather(self, message: str) -> VerificationResult:
        normalized = _normalize(message)
        location_query = self._weather_location(message) or self.default_location
        try:
            locations = await self._get_json(
                self._GEOCODING_URL,
                {"name": location_query, "count": 5, "language": "es", "format": "json"},
            )
            results = locations.get("results")
            if not isinstance(results, list) or not results:
                return VerificationResult(
                    f"No encontré una ubicación verificable llamada {location_query}."
                )
            place = results[0]
            latitude = float(place["latitude"])
            longitude = float(place["longitude"])
            place_name = str(place.get("name") or location_query)
            country = str(place.get("country") or "").strip()
            label = f"{place_name}, {country}" if country else place_name
            forecast = await self._get_json(
                self._WEATHER_URL,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,apparent_temperature,relative_humidity_2m,"
                        "precipitation,weather_code,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "forecast_days": 3,
                    "timezone": "auto",
                },
            )
            if "manana" in normalized:
                return self._tomorrow_answer(label, forecast)
            return self._current_answer(label, forecast)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return VerificationResult(
                "No pude consultar Open-Meteo en este momento, así que prefiero no inventar "
                "el clima."
            )

    @classmethod
    def _current_answer(cls, label: str, forecast: dict[str, Any]) -> VerificationResult:
        current = forecast["current"]
        temperature = round(float(current["temperature_2m"]), 1)
        apparent = round(float(current["apparent_temperature"]), 1)
        humidity = round(float(current["relative_humidity_2m"]))
        precipitation = round(float(current.get("precipitation", 0)), 1)
        condition = cls._WEATHER_CODES.get(
            int(current.get("weather_code", -1)),
            "condiciones variables",
        )
        observed = str(current.get("time", "hora local")).replace("T", " a las ")
        answer = (
            f"Según Open-Meteo, en {label} hay {temperature} grados Celsius, con sensación de "
            f"{apparent}, {condition} y {humidity} por ciento de humedad. "
            f"Precipitación reciente: {precipitation} milímetros; dato de {observed}."
        )
        return VerificationResult(answer, sources=("Open-Meteo",))

    @classmethod
    def _tomorrow_answer(cls, label: str, forecast: dict[str, Any]) -> VerificationResult:
        daily = forecast["daily"]
        date_value = str(daily["time"][1])
        minimum = round(float(daily["temperature_2m_min"][1]), 1)
        maximum = round(float(daily["temperature_2m_max"][1]), 1)
        rain = round(float(daily["precipitation_probability_max"][1]))
        condition = cls._WEATHER_CODES.get(int(daily["weather_code"][1]), "condiciones variables")
        answer = (
            f"Según el pronóstico de Open-Meteo para {label}, mañana {date_value} se espera "
            f"{condition}, entre {minimum} y {maximum} grados Celsius, con hasta {rain} por ciento "
            "de probabilidad de precipitacion."
        )
        return VerificationResult(answer, sources=("Open-Meteo",))

    @classmethod
    def _needs_factual_lookup(cls, normalized: str) -> bool:
        if any(marker in normalized for marker in cls._PERSONAL_MARKERS):
            return False
        if any(marker in normalized for marker in cls._CONVERSATIONAL_MARKERS):
            return False
        return any(marker in normalized for marker in cls._QUESTION_MARKERS)

    async def _wikipedia(self, query: str) -> VerificationResult:
        try:
            payload = await self._get_json(
                self._WIKIPEDIA_URL,
                {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": query[:300],
                    "gsrnamespace": 0,
                    "gsrlimit": 3,
                    "prop": "extracts|info",
                    "exintro": 1,
                    "explaintext": 1,
                    "inprop": "url",
                    "format": "json",
                    "formatversion": 2,
                    "origin": "*",
                },
            )
            pages = payload.get("query", {}).get("pages", [])
            if not isinstance(pages, list) or not pages:
                return VerificationResult(
                    "No encontre una fuente suficientemente clara para comprobar ese dato."
                )
            excerpts: list[str] = []
            sources: list[str] = []
            for page in pages[:3]:
                if not isinstance(page, dict):
                    continue
                title = str(page.get("title", "Articulo"))[:200]
                extract = " ".join(str(page.get("extract", "")).split())[:1_200]
                url = str(page.get("fullurl", ""))
                if not extract:
                    continue
                excerpts.append(
                    f"Fuente: Wikipedia en español — {title}\nURL: {url}\nResumen: {extract}"
                )
                if url:
                    sources.append(url)
            if not excerpts:
                return VerificationResult(
                    "No encontre contenido verificable para responder con seguridad."
                )
            return VerificationResult(evidence="\n\n".join(excerpts), sources=tuple(sources))
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return VerificationResult(
                "No pude consultar una fuente externa en este momento, así que prefiero no "
                "inventar la respuesta."
            )

    async def verify(self, message: str) -> VerificationResult | None:
        if not self.enabled:
            return None
        normalized = _normalize(message.strip())
        if any(marker in normalized for marker in self._WEATHER_MARKERS):
            return await self._weather(message)
        if not self._needs_factual_lookup(normalized):
            return None
        if any(marker in normalized for marker in self._UNSUPPORTED_LIVE_MARKERS):
            return VerificationResult(
                "Todavía no tengo una fuente en tiempo real configurada para ese dato cambiante, "
                "así que prefiero no adivinarlo."
            )
        return await self._wikipedia(message.strip())
