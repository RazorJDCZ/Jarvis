from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    performance: Literal["adaptive", "economy", "quality"] = "adaptive"
    voice: Literal["em_alex", "em_santa", "ef_dora"] = "em_alex"
    voice_speed: float = Field(default=1.0, ge=0.75, le=1.25)
    proactive: bool = False
    briefing_hour: int = Field(default=8, ge=0, le=23)
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=7, ge=0, le=23)


class PreferenceStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def get(self) -> Preferences:
        with self._lock:
            try:
                return Preferences.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return Preferences()

    def save(self, value: Preferences) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value.model_dump()), encoding="utf-8")
            temporary.replace(self.path)

    def quiet(self, hour: int) -> bool:
        p = self.get()
        if p.quiet_start == p.quiet_end:
            return False
        if p.quiet_start < p.quiet_end:
            return p.quiet_start <= hour < p.quiet_end
        return hour >= p.quiet_start or hour < p.quiet_end
