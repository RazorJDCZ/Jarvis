from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jarvis.actions.models import ActionOutcome, PreparedAction, PreparedWorkflow

_SENSITIVE_ARGUMENTS = frozenset({"text", "value", "password", "content", "question"})
_SENSITIVE_RESULTS = frozenset(
    {
        "browser.list_tabs",
        "browser.read",
        "clipboard.read",
        "screen.ask",
        "screen.click",
        "screen.describe",
        "screen.find",
        "ui.inspect",
        "window.current",
        "window.list",
    }
)


class ActionAuditLog:
    def __init__(self, path: Path, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    @staticmethod
    def _redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "<redacted>"
                    if str(key).casefold() in _SENSITIVE_ARGUMENTS
                    else ActionAuditLog._redact_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [ActionAuditLog._redact_value(item) for item in value]
        return value

    @staticmethod
    def _redact(arguments: dict[str, Any]) -> dict[str, Any]:
        return ActionAuditLog._redact_value(arguments)

    def record(
        self,
        session_id: str,
        action: PreparedAction | PreparedWorkflow,
        outcome: ActionOutcome,
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "action": action.name.value,
            "risk": action.risk.value,
            "source": action.source.value,
            "arguments": self._redact(action.arguments),
            "status": outcome.status.value,
            "message": (
                "<redacted>" if action.name.value in _SENSITIVE_RESULTS else outcome.message[:300]
            ),
        }
        encoded = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                    rotated = self.path.with_suffix(self.path.suffix + ".1")
                    rotated.unlink(missing_ok=True)
                    self.path.replace(rotated)
                with self.path.open("a", encoding="utf-8", newline="\n") as audit_file:
                    audit_file.write(encoded)
        except OSError:
            # The action result must never be changed by a diagnostic logging failure.
            return

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with self._lock:
                lines = self.path.read_text(encoding="utf-8").splitlines()[-max(1, limit) :]
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                entries.append(payload)
        return entries
