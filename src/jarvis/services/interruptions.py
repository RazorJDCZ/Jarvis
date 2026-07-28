from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


class VoiceInterruptionMatcher:
    _COMMANDS = frozenset(
        {
            "basta",
            "callate",
            "deja de hablar",
            "detente",
            "es suficiente",
            "para",
            "para de hablar",
            "silencio",
            "suficiente",
            "ya",
            "ya es suficiente",
        }
    )

    def __init__(self, wake_word: str) -> None:
        self.wake_word = _normalize(wake_word)

    def matches(self, transcript: str) -> bool:
        normalized = _normalize(transcript)
        match = re.fullmatch(
            rf"(?:(?:oye|hey) )?{re.escape(self.wake_word)}(?: |, )?(.+)",
            normalized,
        )
        return match is not None and match.group(1).strip() in self._COMMANDS
