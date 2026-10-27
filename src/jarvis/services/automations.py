from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

AUTOMATION_KINDS = frozenset(
    {
        "daily_briefing",
        "important_mail",
        "calendar_soon",
        "weather_daily",
        "deadline_watch",
    }
)
DEFAULT_RULE_IDS = frozenset(
    {
        "morning-briefing",
        "important-mail",
        "calendar-soon",
        "weather-daily",
        "deadline-watch",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _clean(value: str, maximum: int) -> str:
    return " ".join(str(value).split()).strip()[:maximum]


@dataclass(frozen=True, slots=True)
class AutomationRule:
    rule_id: str
    name: str
    kind: str
    enabled: bool
    hour: int
    lead_minutes: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AutomationJob:
    job_id: str
    session_id: str
    dedupe_key: str
    payload: dict[str, object]
    attempts: int
    max_attempts: int


class AutomationStore:
    """Small declarative rule store; rules can only emit private notifications."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA secure_delete=ON;
                CREATE TABLE IF NOT EXISTS automation_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    lead_minutes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS automation_runs (
                    rule_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    run_key TEXT NOT NULL,
                    fired_at TEXT NOT NULL,
                    PRIMARY KEY(rule_id, session_id, run_key)
                );
                CREATE TABLE IF NOT EXISTS automation_jobs (
                    job_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 4,
                    next_attempt REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(session_id, dedupe_key)
                );
                CREATE INDEX IF NOT EXISTS idx_automation_jobs_due
                    ON automation_jobs(state, next_attempt);
                """
            )
            if connection.execute("SELECT COUNT(*) FROM automation_rules").fetchone()[0] == 0:
                now = _now()
                connection.executemany(
                    "INSERT INTO automation_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        (
                            "morning-briefing",
                            "Resumen inteligente de la mañana",
                            "daily_briefing",
                            1,
                            8,
                            30,
                            now,
                            now,
                        ),
                        (
                            "important-mail",
                            "Resumen de correos importantes",
                            "important_mail",
                            0,
                            8,
                            30,
                            now,
                            now,
                        ),
                        (
                            "calendar-soon",
                            "Avisar compromisos próximos",
                            "calendar_soon",
                            0,
                            8,
                            30,
                            now,
                            now,
                        ),
                        (
                            "weather-daily",
                            "Clima antes de empezar el día",
                            "weather_daily",
                            0,
                            7,
                            30,
                            now,
                            now,
                        ),
                        (
                            "deadline-watch",
                            "Avisar fechas límite detectadas en correo",
                            "deadline_watch",
                            0,
                            8,
                            1440,
                            now,
                            now,
                        ),
                    ),
                )
            now = _now()
            connection.execute(
                "INSERT OR IGNORE INTO automation_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "deadline-watch",
                    "Avisar fechas límite detectadas en correo",
                    "deadline_watch",
                    0,
                    8,
                    1440,
                    now,
                    now,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _rule(row: sqlite3.Row) -> AutomationRule:
        return AutomationRule(
            rule_id=str(row["rule_id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            enabled=bool(row["enabled"]),
            hour=int(row["hour"]),
            lead_minutes=int(row["lead_minutes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list(self, *, enabled_only: bool = False) -> tuple[AutomationRule, ...]:
        query = "SELECT * FROM automation_rules"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY kind, name"
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query).fetchall()
        return tuple(self._rule(row) for row in rows)

    def save(
        self,
        *,
        name: str,
        kind: str,
        enabled: bool = True,
        hour: int = 8,
        lead_minutes: int = 30,
        rule_id: str | None = None,
    ) -> AutomationRule:
        safe_name = _clean(name, 160)
        safe_kind = _clean(kind, 40).casefold()
        if not safe_name or safe_kind not in AUTOMATION_KINDS:
            raise ValueError("Automatización no válida")
        if not 0 <= int(hour) <= 23:
            raise ValueError("La hora debe estar entre 0 y 23")
        if not 5 <= int(lead_minutes) <= 1_440:
            raise ValueError("La anticipación debe estar entre 5 y 1440 minutos")
        identifier = rule_id or uuid4().hex
        if len(identifier) > 64 or not all(
            char.isalnum() or char in "-_" for char in identifier
        ):
            raise ValueError("Identificador de automatización no válido")
        now = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            old = connection.execute(
                "SELECT created_at FROM automation_rules WHERE rule_id=?", (identifier,)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO automation_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    name=excluded.name, kind=excluded.kind, enabled=excluded.enabled,
                    hour=excluded.hour, lead_minutes=excluded.lead_minutes,
                    updated_at=excluded.updated_at
                """,
                (
                    identifier,
                    safe_name,
                    safe_kind,
                    int(bool(enabled)),
                    int(hour),
                    int(lead_minutes),
                    str(old["created_at"]) if old else now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM automation_rules WHERE rule_id=?", (identifier,)
            ).fetchone()
        return self._rule(row)

    def delete(self, rule_id: str) -> bool:
        if rule_id in DEFAULT_RULE_IDS:
            return False
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM automation_rules WHERE rule_id=?", (rule_id,)
            )
            connection.execute("DELETE FROM automation_runs WHERE rule_id=?", (rule_id,))
        return cursor.rowcount == 1

    def claim(self, rule_id: str, session_id: str, run_key: str) -> bool:
        """Atomically reserve one notification, preventing duplicate deliveries."""

        if len(run_key) > 240 or len(session_id) > 128:
            return False
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO automation_runs VALUES (?, ?, ?, ?)",
                    (rule_id, session_id, run_key, _now()),
                )
                cutoff = (datetime.now(UTC) - timedelta(days=45)).isoformat()
                connection.execute("DELETE FROM automation_runs WHERE fired_at < ?", (cutoff,))
            return True
        except sqlite3.IntegrityError:
            return False

    def enqueue_notification(
        self,
        session_id: str,
        dedupe_key: str,
        payload: dict[str, object],
        *,
        max_attempts: int = 4,
    ) -> bool:
        safe_session = _clean(session_id, 128)
        safe_key = _clean(dedupe_key, 240)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if (
            not safe_session
            or not safe_key
            or len(encoded.encode("utf-8")) > 8_192
            or not 1 <= int(max_attempts) <= 10
        ):
            raise ValueError("Trabajo de automatización no válido")
        now = _now()
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO automation_jobs(
                        job_id, session_id, dedupe_key, payload_json, state, attempts,
                        max_attempts, next_attempt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        safe_session,
                        safe_key,
                        encoded,
                        int(max_attempts),
                        time.time(),
                        now,
                        now,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def due_jobs(self, *, limit: int = 20) -> tuple[AutomationJob, ...]:
        safe_limit = max(1, min(int(limit), 100))
        now_epoch = time.time()
        now_text = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE automation_jobs SET state='pending' "
                "WHERE state='running' AND next_attempt<=?",
                (now_epoch,),
            )
            rows = connection.execute(
                """
                SELECT * FROM automation_jobs
                WHERE state='pending' AND next_attempt<=?
                ORDER BY next_attempt, created_at LIMIT ?
                """,
                (now_epoch, safe_limit),
            ).fetchall()
            jobs: list[AutomationJob] = []
            for row in rows:
                connection.execute(
                    """
                    UPDATE automation_jobs SET state='running', attempts=attempts+1,
                        next_attempt=?, updated_at=? WHERE job_id=? AND state='pending'
                    """,
                    (now_epoch + 120, now_text, row["job_id"]),
                )
                try:
                    payload = json.loads(str(row["payload_json"]))
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                jobs.append(
                    AutomationJob(
                        job_id=str(row["job_id"]),
                        session_id=str(row["session_id"]),
                        dedupe_key=str(row["dedupe_key"]),
                        payload=payload,
                        attempts=int(row["attempts"]) + 1,
                        max_attempts=int(row["max_attempts"]),
                    )
                )
        return tuple(jobs)

    def finish_job(self, job_id: str, *, error: str = "") -> bool:
        safe_id = _clean(job_id, 64)
        now = _now()
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT attempts,max_attempts FROM automation_jobs WHERE job_id=?",
                (safe_id,),
            ).fetchone()
            if row is None:
                return False
            if not error:
                cursor = connection.execute(
                    "UPDATE automation_jobs SET state='completed',last_error='',updated_at=? "
                    "WHERE job_id=?",
                    (now, safe_id),
                )
            elif int(row["attempts"]) >= int(row["max_attempts"]):
                cursor = connection.execute(
                    "UPDATE automation_jobs SET state='failed',last_error=?,updated_at=? "
                    "WHERE job_id=?",
                    (_clean(error, 300), now, safe_id),
                )
            else:
                delay = min(900, 10 * (2 ** max(0, int(row["attempts"]) - 1)))
                cursor = connection.execute(
                    """
                    UPDATE automation_jobs SET state='pending',last_error=?,next_attempt=?,
                        updated_at=? WHERE job_id=?
                    """,
                    (_clean(error, 300), time.time() + delay, now, safe_id),
                )
            connection.execute(
                "DELETE FROM automation_jobs WHERE state='completed' AND updated_at<?",
                ((datetime.now(UTC) - timedelta(days=7)).isoformat(),),
            )
        return cursor.rowcount == 1

    def job_stats(self) -> dict[str, int]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT state,COUNT(*) AS total FROM automation_jobs GROUP BY state"
            ).fetchall()
        result = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for row in rows:
            state = str(row["state"])
            if state in result:
                result[state] = int(row["total"])
        return result
