from __future__ import annotations

import calendar
import json
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(password|contrase(?:ñ|n)a|token|api[_ -]?key|secret)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "clipboard",
        "content",
        "cookie",
        "file_content",
        "frame",
        "image",
        "password",
        "prompt",
        "secret",
        "text",
        "token",
        "value",
    }
)
_RECURRENCES = frozenset({"none", "daily", "weekly", "monthly"})
_DECISIONS = frozenset({"allow", "ask"})
_AUTOAPPROVABLE_RISKS = frozenset({"low", "medium"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("La fecha debe usar formato ISO 8601.") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _bounded(value: str, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    normalized = " ".join(str(value).split())
    if not normalized and not allow_empty:
        raise ValueError(f"{field} no puede estar vacío.")
    if len(normalized) > maximum:
        raise ValueError(f"{field} supera el límite de {maximum} caracteres.")
    return normalized


def _redact_text(value: str, maximum: int) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda match: f"{match.group(1)}=<redacted>" if match.lastindex else "<redacted>",
            redacted,
        )
    normalized = " ".join(redacted.split())
    if len(normalized) > maximum:
        return normalized[: maximum - 1].rstrip() + "…"
    return normalized


def _safe_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "<truncated>"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _redact_text(value, 500)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= 40:
                result["<truncated>"] = True
                break
            key = _redact_text(str(raw_key), 80)
            result[key] = (
                "<redacted>"
                if key.casefold() in _SENSITIVE_KEYS
                else _safe_metadata(item, depth=depth + 1)
            )
        return result
    if isinstance(value, list | tuple | set | frozenset):
        items = list(value)
        rendered = [_safe_metadata(item, depth=depth + 1) for item in items[:40]]
        if len(items) > 40:
            rendered.append("<truncated>")
        return rendered
    return _redact_text(str(value), 200)


def _metadata_json(metadata: Mapping[str, Any] | None, *, sensitive: bool) -> str:
    payload: Any = {"redacted": True} if sensitive else _safe_metadata(metadata or {})
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 8_192:
        encoded = json.dumps({"truncated": True}, separators=(",", ":"))
    return encoded


class _SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class TraceSpan:
    sequence: int
    name: str
    status: str
    detail: str
    metadata: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class TraceRecord:
    trace_id: str
    session_id: str
    input_summary: str
    channel: str
    status: str
    started_at: str
    finished_at: str | None
    spans: tuple[TraceSpan, ...]


class TraceStore(_SQLiteStore):
    """Bounded, redacted execution traces stored only in an injected SQLite path."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        max_spans: int = 200,
        max_records_per_session: int = 500,
    ) -> None:
        super().__init__(path)
        self._clock = clock or _utc_now
        self.max_spans = min(max(1, int(max_spans)), 1_000)
        self.max_records_per_session = min(max(10, int(max_records_per_session)), 10_000)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS capability_traces (
                    trace_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    input_summary TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_capability_traces_session_started
                    ON capability_traces(session_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS capability_trace_spans (
                    trace_id TEXT NOT NULL REFERENCES capability_traces(trace_id)
                        ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(trace_id, sequence)
                );
                """
            )

    def start(self, session_id: str, input_summary: str, channel: str) -> str:
        session = _bounded(session_id, field="session_id", maximum=128)
        summary = _redact_text(input_summary, 500)
        if not summary:
            raise ValueError("input_summary no puede estar vacío.")
        safe_channel = _bounded(channel, field="channel", maximum=40).casefold()
        trace_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO capability_traces(
                    trace_id, session_id, input_summary, channel, status, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (trace_id, session, summary, safe_channel, _iso(self._clock())),
            )
            connection.execute(
                """
                DELETE FROM capability_traces
                WHERE trace_id IN (
                    SELECT trace_id FROM capability_traces
                    WHERE session_id = ?
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (session, self.max_records_per_session),
            )
        return trace_id

    def add_span(
        self,
        trace_id: str,
        name: str,
        status: str,
        detail: str = "",
        metadata: Mapping[str, Any] | None = None,
        sensitive: bool = False,
    ) -> bool:
        safe_id = _bounded(trace_id, field="trace_id", maximum=64)
        safe_name = _bounded(name, field="name", maximum=80)
        safe_status = _bounded(status, field="status", maximum=40).casefold()
        safe_detail = "<redacted>" if sensitive else _redact_text(detail, 500)
        encoded_metadata = _metadata_json(metadata, sensitive=sensitive)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM capability_trace_spans WHERE trace_id = ?",
                (safe_id,),
            ).fetchone()
            exists = connection.execute(
                "SELECT 1 FROM capability_traces WHERE trace_id = ?",
                (safe_id,),
            ).fetchone()
            if exists is None or row is None or int(row["total"]) >= self.max_spans:
                return False
            sequence = int(row["total"]) + 1
            connection.execute(
                """
                INSERT INTO capability_trace_spans(
                    trace_id, sequence, name, status, detail, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_id,
                    sequence,
                    safe_name,
                    safe_status,
                    safe_detail,
                    encoded_metadata,
                    _iso(self._clock()),
                ),
            )
        return True

    def finish(self, trace_id: str, status: str) -> bool:
        safe_id = _bounded(trace_id, field="trace_id", maximum=64)
        safe_status = _bounded(status, field="status", maximum=40).casefold()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE capability_traces
                SET status = ?, finished_at = ?
                WHERE trace_id = ?
                """,
                (safe_status, _iso(self._clock()), safe_id),
            )
        return cursor.rowcount == 1

    def recent(self, session_id: str, limit: int = 30) -> tuple[TraceRecord, ...]:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_limit = min(max(1, int(limit)), 100)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT trace_id FROM capability_traces
                WHERE session_id = ?
                ORDER BY started_at DESC, rowid DESC
                LIMIT ?
                """,
                (session, safe_limit),
            ).fetchall()
        records = [self.get(str(row["trace_id"]), session) for row in rows]
        return tuple(record for record in records if record is not None)

    def get(self, trace_id: str, session_id: str) -> TraceRecord | None:
        safe_id = _bounded(trace_id, field="trace_id", maximum=64)
        session = _bounded(session_id, field="session_id", maximum=128)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM capability_traces
                WHERE trace_id = ? AND session_id = ?
                """,
                (safe_id, session),
            ).fetchone()
            if row is None:
                return None
            span_rows = connection.execute(
                """
                SELECT * FROM capability_trace_spans
                WHERE trace_id = ? ORDER BY sequence
                """,
                (safe_id,),
            ).fetchall()
        spans = tuple(
            TraceSpan(
                sequence=int(span["sequence"]),
                name=str(span["name"]),
                status=str(span["status"]),
                detail=str(span["detail"]),
                metadata=json.loads(str(span["metadata_json"])),
                created_at=str(span["created_at"]),
            )
            for span in span_rows
        )
        return TraceRecord(
            trace_id=str(row["trace_id"]),
            session_id=str(row["session_id"]),
            input_summary=str(row["input_summary"]),
            channel=str(row["channel"]),
            status=str(row["status"]),
            started_at=str(row["started_at"]),
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
            spans=spans,
        )


@dataclass(frozen=True, slots=True)
class PermissionRule:
    action: str
    remote: bool
    decision: str
    created_at: str
    expires_at: str | None


class PermissionStore(_SQLiteStore):
    """Context-scoped permission preferences; it never overrides high-risk policy."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        super().__init__(path)
        self._clock = clock or _utc_now
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_permissions (
                    action TEXT NOT NULL,
                    remote INTEGER NOT NULL CHECK(remote IN (0, 1)),
                    decision TEXT NOT NULL CHECK(decision IN ('allow', 'ask')),
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    PRIMARY KEY(action, remote)
                )
                """
            )

    @staticmethod
    def _action(value: str) -> str:
        return _bounded(value, field="action", maximum=120).casefold()

    def set(
        self,
        action: str,
        remote: bool,
        decision: str,
        expires_at: datetime | str | None = None,
    ) -> PermissionRule:
        safe_action = self._action(action)
        safe_decision = _bounded(decision, field="decision", maximum=10).casefold()
        if safe_decision not in _DECISIONS:
            raise ValueError("decision debe ser 'allow' o 'ask'.")
        expiry = _as_utc(expires_at) if expires_at is not None else None
        now = _as_utc(self._clock())
        if expiry is not None and expiry <= now:
            raise ValueError("La expiración debe estar en el futuro.")
        created_at = _iso(now)
        expiry_text = _iso(expiry) if expiry is not None else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO capability_permissions(
                    action, remote, decision, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(action, remote) DO UPDATE SET
                    decision = excluded.decision,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (safe_action, int(bool(remote)), safe_decision, created_at, expiry_text),
            )
        return PermissionRule(safe_action, bool(remote), safe_decision, created_at, expiry_text)

    def list(self, remote: bool | None = None) -> tuple[PermissionRule, ...]:
        now = _iso(self._clock())
        query = """
            SELECT * FROM capability_permissions
            WHERE (expires_at IS NULL OR expires_at > ?)
        """
        parameters: list[object] = [now]
        if remote is not None:
            query += " AND remote = ?"
            parameters.append(int(remote))
        query += " ORDER BY action, remote"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._rule(row) for row in rows)

    def delete(self, action: str, remote: bool) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM capability_permissions WHERE action = ? AND remote = ?",
                (self._action(action), int(bool(remote))),
            )
        return cursor.rowcount == 1

    def is_allowed(self, action: str, remote: bool, risk: str | Any = "low") -> bool:
        risk_value = getattr(risk, "value", risk)
        normalized_risk = str(risk_value).strip().casefold()
        # New/invalid risk classes must never inherit a remembered permission. An
        # allow-list keeps this security boundary closed when the enum evolves.
        if normalized_risk not in _AUTOAPPROVABLE_RISKS:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM capability_permissions
                WHERE action = ? AND remote = ?
                """,
                (self._action(action), int(bool(remote))),
            ).fetchone()
        if row is None or str(row["decision"]) != "allow":
            return False
        expires_at = row["expires_at"]
        return expires_at is None or _as_utc(str(expires_at)) > _as_utc(self._clock())

    @staticmethod
    def _rule(row: sqlite3.Row) -> PermissionRule:
        return PermissionRule(
            action=str(row["action"]),
            remote=bool(row["remote"]),
            decision=str(row["decision"]),
            created_at=str(row["created_at"]),
            expires_at=str(row["expires_at"]) if row["expires_at"] else None,
        )


@dataclass(frozen=True, slots=True)
class Reminder:
    reminder_id: str
    session_id: str
    title: str
    detail: str
    due_at: str
    recurrence: str
    created_at: str
    last_fired_at: str | None
    cancelled_at: str | None


class ReminderStore(_SQLiteStore):
    """Persistent UTC reminders with bounded recurrence and soft cancellation."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        max_per_session: int = 1_000,
    ) -> None:
        super().__init__(path)
        self._clock = clock or _utc_now
        self.max_per_session = min(max(1, int(max_per_session)), 10_000)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS capability_reminders (
                    reminder_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    recurrence TEXT NOT NULL,
                    anchor_day INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_fired_at TEXT,
                    cancelled_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_capability_reminders_due
                    ON capability_reminders(session_id, due_at);
                """
            )

    def create(
        self,
        session_id: str,
        title: str,
        due_at: datetime | str,
        recurrence: str = "none",
        detail: str = "",
    ) -> Reminder:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_title = _bounded(title, field="title", maximum=200)
        safe_detail = _bounded(detail, field="detail", maximum=2_000, allow_empty=True)
        safe_recurrence = _bounded(recurrence, field="recurrence", maximum=10).casefold()
        if safe_recurrence not in _RECURRENCES:
            raise ValueError("Recurrencia no permitida.")
        due = _as_utc(due_at)
        with self._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) AS total FROM capability_reminders
                WHERE session_id = ? AND cancelled_at IS NULL
                    AND NOT (recurrence = 'none' AND last_fired_at IS NOT NULL)
                """,
                (session,),
            ).fetchone()
            if count is not None and int(count["total"]) >= self.max_per_session:
                raise ValueError("Se alcanzó el límite de recordatorios activos.")
            reminder_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO capability_reminders(
                    reminder_id, session_id, title, detail, due_at, recurrence,
                    anchor_day, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reminder_id,
                    session,
                    safe_title,
                    safe_detail,
                    _iso(due),
                    safe_recurrence,
                    due.day,
                    _iso(self._clock()),
                ),
            )
        reminder = self._get(reminder_id, session)
        if reminder is None:  # pragma: no cover - SQLite insert/read invariant
            raise RuntimeError("No se pudo recuperar el recordatorio creado.")
        return reminder

    def list(
        self,
        session_id: str,
        *,
        include_cancelled: bool = False,
        limit: int = 100,
    ) -> tuple[Reminder, ...]:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_limit = min(max(1, int(limit)), 1_000)
        query = "SELECT * FROM capability_reminders WHERE session_id = ?"
        if not include_cancelled:
            query += (
                " AND cancelled_at IS NULL"
                " AND NOT (recurrence = 'none' AND last_fired_at IS NOT NULL)"
            )
        query += " ORDER BY due_at, created_at LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (session, safe_limit)).fetchall()
        return tuple(self._reminder(row) for row in rows)

    def cancel(self, reminder_id: str, session_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE capability_reminders SET cancelled_at = ?
                WHERE reminder_id = ? AND session_id = ? AND cancelled_at IS NULL
                """,
                (
                    _iso(self._clock()),
                    _bounded(reminder_id, field="reminder_id", maximum=64),
                    _bounded(session_id, field="session_id", maximum=128),
                ),
            )
        return cursor.rowcount == 1

    def due(
        self,
        session_id: str,
        at: datetime | str | None = None,
        *,
        limit: int = 100,
    ) -> tuple[Reminder, ...]:
        session = _bounded(session_id, field="session_id", maximum=128)
        cutoff = _as_utc(at) if at is not None else _as_utc(self._clock())
        safe_limit = min(max(1, int(limit)), 1_000)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM capability_reminders
                WHERE session_id = ? AND cancelled_at IS NULL AND due_at <= ?
                    AND NOT (recurrence = 'none' AND last_fired_at IS NOT NULL)
                ORDER BY due_at, created_at LIMIT ?
                """,
                (session, _iso(cutoff), safe_limit),
            ).fetchall()
        return tuple(self._reminder(row) for row in rows)

    def session_ids(self) -> tuple[str, ...]:
        """Return only sessions that currently own an active reminder."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT session_id FROM capability_reminders
                WHERE cancelled_at IS NULL
                    AND NOT (recurrence = 'none' AND last_fired_at IS NOT NULL)
                ORDER BY session_id
                """
            ).fetchall()
        return tuple(str(row["session_id"]) for row in rows)

    def mark_fired(
        self,
        reminder_id: str,
        session_id: str,
        fired_at: datetime | str | None = None,
    ) -> Reminder | None:
        safe_id = _bounded(reminder_id, field="reminder_id", maximum=64)
        session = _bounded(session_id, field="session_id", maximum=128)
        fired = _as_utc(fired_at) if fired_at is not None else _as_utc(self._clock())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM capability_reminders
                WHERE reminder_id = ? AND session_id = ? AND cancelled_at IS NULL
                """,
                (safe_id, session),
            ).fetchone()
            if row is None:
                return None
            recurrence = str(row["recurrence"])
            due_at = _as_utc(str(row["due_at"]))
            next_due = (
                due_at
                if recurrence == "none"
                else self._advance_after(
                    due_at,
                    recurrence,
                    int(row["anchor_day"]),
                    fired,
                )
            )
            connection.execute(
                """
                UPDATE capability_reminders SET last_fired_at = ?, due_at = ?
                WHERE reminder_id = ? AND session_id = ?
                """,
                (_iso(fired), _iso(next_due), safe_id, session),
            )
        return self._get(safe_id, session)

    @staticmethod
    def _advance_after(
        due: datetime,
        recurrence: str,
        anchor_day: int,
        after: datetime,
    ) -> datetime:
        if recurrence == "daily":
            periods = max(1, (after - due) // timedelta(days=1) + 1)
            return due + periods * timedelta(days=1)
        if recurrence == "weekly":
            periods = max(1, (after - due) // timedelta(days=7) + 1)
            return due + periods * timedelta(days=7)
        months = max(1, (after.year - due.year) * 12 + after.month - due.month)
        candidate = ReminderStore._add_months(due, months, anchor_day)
        if candidate <= after:
            candidate = ReminderStore._add_months(due, months + 1, anchor_day)
        return candidate

    @staticmethod
    def _add_months(value: datetime, months: int, anchor_day: int) -> datetime:
        month_index = value.year * 12 + (value.month - 1) + months
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        day = min(anchor_day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)

    def _get(self, reminder_id: str, session_id: str) -> Reminder | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM capability_reminders
                WHERE reminder_id = ? AND session_id = ?
                """,
                (reminder_id, session_id),
            ).fetchone()
        return self._reminder(row) if row is not None else None

    @staticmethod
    def _reminder(row: sqlite3.Row) -> Reminder:
        return Reminder(
            reminder_id=str(row["reminder_id"]),
            session_id=str(row["session_id"]),
            title=str(row["title"]),
            detail=str(row["detail"]),
            due_at=str(row["due_at"]),
            recurrence=str(row["recurrence"]),
            created_at=str(row["created_at"]),
            last_fired_at=str(row["last_fired_at"]) if row["last_fired_at"] else None,
            cancelled_at=str(row["cancelled_at"]) if row["cancelled_at"] else None,
        )


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_id: str
    session_id: str
    title: str
    origin: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeResult:
    source_id: str
    title: str
    origin: str
    excerpt: str
    citation: str


class KnowledgeStore(_SQLiteStore):
    """Session-isolated local text index with an SQLite LIKE fallback."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        enable_fts: bool = True,
        max_sources_per_session: int = 500,
    ) -> None:
        super().__init__(path)
        self._clock = clock or _utc_now
        self.max_sources_per_session = min(max(1, int(max_sources_per_session)), 10_000)
        self.fts_available = False
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS capability_knowledge_sources (
                    source_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(session_id, origin)
                );
                CREATE INDEX IF NOT EXISTS idx_capability_knowledge_session
                    ON capability_knowledge_sources(session_id, updated_at DESC);
                """
            )
            if enable_fts:
                try:
                    connection.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS capability_knowledge_fts
                        USING fts5(source_id UNINDEXED, title, text)
                        """
                    )
                except sqlite3.OperationalError:
                    self.fts_available = False
                else:
                    self.fts_available = True

    def upsert_source(
        self,
        session_id: str,
        title: str,
        text: str,
        origin: str,
    ) -> KnowledgeSource:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_title = _bounded(title, field="title", maximum=300)
        safe_text = str(text).strip()
        if not safe_text:
            raise ValueError("text no puede estar vacío.")
        if len(safe_text) > 1_000_000:
            raise ValueError("text supera el límite de 1000000 caracteres.")
        safe_origin = _bounded(origin, field="origin", maximum=1_000)
        now = _iso(self._clock())
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT source_id, created_at FROM capability_knowledge_sources
                WHERE session_id = ? AND origin = ?
                """,
                (session, safe_origin),
            ).fetchone()
            if existing is None:
                count = connection.execute(
                    """
                    SELECT COUNT(*) AS total FROM capability_knowledge_sources
                    WHERE session_id = ?
                    """,
                    (session,),
                ).fetchone()
                if count is not None and int(count["total"]) >= self.max_sources_per_session:
                    raise ValueError("Se alcanzó el límite de fuentes de esta sesión.")
            source_id = str(existing["source_id"]) if existing is not None else uuid4().hex
            created_at = str(existing["created_at"]) if existing is not None else now
            connection.execute(
                """
                INSERT INTO capability_knowledge_sources(
                    source_id, session_id, title, text, origin, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, origin) DO UPDATE SET
                    title = excluded.title,
                    text = excluded.text,
                    updated_at = excluded.updated_at
                """,
                (source_id, session, safe_title, safe_text, safe_origin, created_at, now),
            )
            if self.fts_available:
                try:
                    connection.execute(
                        "DELETE FROM capability_knowledge_fts WHERE source_id = ?",
                        (source_id,),
                    )
                    connection.execute(
                        """
                        INSERT INTO capability_knowledge_fts(source_id, title, text)
                        VALUES (?, ?, ?)
                        """,
                        (source_id, safe_title, safe_text),
                    )
                except sqlite3.OperationalError:
                    self.fts_available = False
        return KnowledgeSource(source_id, session, safe_title, safe_origin, created_at, now)

    def search(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> tuple[KnowledgeResult, ...]:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_query = _bounded(query, field="query", maximum=500)
        safe_limit = min(max(1, int(limit)), 20)
        tokens = tuple(
            token
            for token in dict.fromkeys(re.findall(r"\w+", safe_query.casefold(), re.UNICODE))
            if any(character.isalnum() for character in token)
        )[:12]
        rows: list[sqlite3.Row] = []
        if self.fts_available and tokens:
            match_query = " OR ".join(
                f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens
            )
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT source.* FROM capability_knowledge_fts AS search
                        JOIN capability_knowledge_sources AS source
                            ON source.source_id = search.source_id
                        WHERE source.session_id = ?
                            AND capability_knowledge_fts MATCH ?
                        ORDER BY bm25(capability_knowledge_fts), source.updated_at DESC
                        LIMIT ?
                        """,
                        (session, match_query, safe_limit),
                    ).fetchall()
            except sqlite3.OperationalError:
                self.fts_available = False
                rows = []
        if not rows:
            escaped = safe_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            token_patterns = [
                "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                for token in tokens
            ]
            clauses = ["(title LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\')"]
            parameters: list[object] = [pattern, pattern]
            for token_pattern in token_patterns:
                clauses.append("(title LIKE ? OR text LIKE ?)")
                parameters.extend((token_pattern, token_pattern))
            where = " OR ".join(clauses)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM capability_knowledge_sources
                    WHERE session_id = ? AND ({where})
                    ORDER BY updated_at DESC LIMIT ?
                    """,  # noqa: S608 - clauses are fixed literals; all values are bound.
                    [session, *parameters, safe_limit],
                ).fetchall()
        return tuple(self._result(row, tokens) for row in rows)

    def list_sources(self, session_id: str, limit: int = 100) -> tuple[KnowledgeSource, ...]:
        session = _bounded(session_id, field="session_id", maximum=128)
        safe_limit = min(max(1, int(limit)), 1_000)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_id, session_id, title, origin, created_at, updated_at
                FROM capability_knowledge_sources
                WHERE session_id = ? ORDER BY updated_at DESC LIMIT ?
                """,
                (session, safe_limit),
            ).fetchall()
        return tuple(
            KnowledgeSource(
                source_id=str(row["source_id"]),
                session_id=str(row["session_id"]),
                title=str(row["title"]),
                origin=str(row["origin"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        )

    @staticmethod
    def _result(row: sqlite3.Row, tokens: tuple[str, ...]) -> KnowledgeResult:
        text = " ".join(str(row["text"]).split())
        lowered = text.casefold()
        positions = [lowered.find(token) for token in tokens if lowered.find(token) >= 0]
        position = min(positions, default=0)
        start = max(0, position - 100)
        end = min(len(text), start + 320)
        excerpt = text[start:end]
        if start:
            excerpt = "…" + excerpt.lstrip()
        if end < len(text):
            excerpt = excerpt.rstrip() + "…"
        title = str(row["title"])
        origin = str(row["origin"])
        return KnowledgeResult(
            source_id=str(row["source_id"]),
            title=title,
            origin=origin,
            excerpt=excerpt,
            citation=f"{title} — {origin}",
        )
