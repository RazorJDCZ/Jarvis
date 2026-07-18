from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


@dataclass(slots=True)
class WakeDecision:
    accepted: bool
    activated: bool = False
    needs_command: bool = False
    command: str = ""


@dataclass(slots=True)
class WakeGate:
    wake_word: str
    window_seconds: int = 10
    max_sessions: int = 64
    _armed_until: dict[str, float] = field(default_factory=dict)

    def evaluate(
        self,
        session_id: str,
        transcript: str,
        require_wake_word: bool,
        now: float | None = None,
    ) -> WakeDecision:
        text = transcript.strip()
        if not text:
            return WakeDecision(accepted=False)
        if not require_wake_word:
            return WakeDecision(accepted=True, command=text)

        current_time = time.monotonic() if now is None else now
        expired_sessions = [
            key for key, deadline in self._armed_until.items() if current_time > deadline
        ]
        for key in expired_sessions:
            self._armed_until.pop(key, None)
        armed_until = self._armed_until.get(session_id, 0.0)
        if current_time <= armed_until:
            self._armed_until.pop(session_id, None)
            return WakeDecision(accepted=True, command=text)

        normalized_text = _normalize(text)
        normalized_wake = re.escape(_normalize(self.wake_word))
        match = re.search(rf"\b{normalized_wake}\b", normalized_text)
        if match is None:
            return WakeDecision(accepted=False)

        # Normalization preserves string length for the expected Latin wake word.
        command = text[match.end() :].lstrip(" ,.:;!?-\u2014")
        if not command:
            while len(self._armed_until) >= max(1, self.max_sessions):
                oldest_session = min(self._armed_until, key=self._armed_until.get)
                self._armed_until.pop(oldest_session, None)
            self._armed_until[session_id] = current_time + self.window_seconds
            return WakeDecision(
                accepted=True,
                activated=True,
                needs_command=True,
            )
        return WakeDecision(
            accepted=True,
            activated=True,
            command=command,
        )
