from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class WorldFact:
    key: str
    value: Any
    source: str
    observed_at: float
    expires_at: float
    confidence: float
    session_id: str

    @property
    def fresh(self) -> bool:
        return time.time() <= self.expires_at


@dataclass(frozen=True, slots=True)
class StoredGoal:
    session_id: str
    original_request: str
    remaining_rounds: int
    remaining_actions: int
    continue_after_current: bool
    remote: bool
    created_at: float
    updated_at: float


class AgentStateStore:
    """Persistent, bounded evidence and goals for the local agent.

    This database stores observations produced by trusted tools. Model prose is never
    promoted into world state, which prevents one hallucination from becoming a fact.
    """

    _MAX_VALUE_BYTES = 32 * 1024
    _MAX_FACTS = 1_000
    _MAX_GOALS = 256
    _MAX_GOAL_ROUNDS = 64
    _MAX_GOAL_ACTIONS = 512
    _TRUSTED_SOURCE_PREFIXES = ("trusted-action:", "trusted-sensor:", "trusted-system:")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=4.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 4000")
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS world_facts (
                    session_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    confidence REAL NOT NULL,
                    PRIMARY KEY (session_id, fact_key)
                );
                CREATE INDEX IF NOT EXISTS idx_world_facts_expiry
                    ON world_facts(expires_at);
                CREATE TABLE IF NOT EXISTS agent_goals (
                    session_id TEXT PRIMARY KEY,
                    original_request TEXT NOT NULL,
                    remaining_rounds INTEGER NOT NULL,
                    remaining_actions INTEGER NOT NULL,
                    continue_after_current INTEGER NOT NULL,
                    remote INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _clean_identifier(value: str, maximum: int) -> str:
        cleaned = value.strip()[:maximum]
        if not cleaned or any(character in cleaned for character in "\x00\r\n"):
            raise ValueError("Identificador de estado inválido")
        return cleaned

    def observe(
        self,
        session_id: str,
        key: str,
        value: Any,
        *,
        source: str,
        ttl_seconds: float = 300.0,
        confidence: float = 1.0,
    ) -> WorldFact:
        session = self._clean_identifier(session_id, 128)
        fact_key = self._clean_identifier(key, 120)
        clean_source = self._clean_identifier(source, 120)
        if not clean_source.startswith(self._TRUSTED_SOURCE_PREFIXES):
            raise ValueError("La fuente no es evidencia confiable")
        if not 1 <= ttl_seconds <= 7 * 24 * 60 * 60:
            raise ValueError("Vigencia de estado inválida")
        if not 0 <= confidence <= 1:
            raise ValueError("Confianza de estado inválida")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > self._MAX_VALUE_BYTES:
            encoded = json.dumps(
                {"summary": str(value)[:8_000], "truncated": True},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        now = time.time()
        expires_at = now + ttl_seconds
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO world_facts
                    (session_id, fact_key, value_json, source, observed_at, expires_at, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, fact_key) DO UPDATE SET
                    value_json=excluded.value_json,
                    source=excluded.source,
                    observed_at=excluded.observed_at,
                    expires_at=excluded.expires_at,
                    confidence=excluded.confidence
                """,
                (session, fact_key, encoded, clean_source, now, expires_at, confidence),
            )
            connection.execute("DELETE FROM world_facts WHERE expires_at < ?", (now,))
            connection.execute(
                """
                DELETE FROM world_facts WHERE rowid IN (
                    SELECT rowid FROM world_facts
                    ORDER BY observed_at DESC LIMIT -1 OFFSET ?
                )
                """,
                (self._MAX_FACTS,),
            )
        return WorldFact(fact_key, value, clean_source, now, expires_at, confidence, session)

    def facts(self, session_id: str, *, limit: int = 12) -> tuple[WorldFact, ...]:
        session = self._clean_identifier(session_id, 128)
        now = time.time()
        safe_limit = max(1, min(limit, 50))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, fact_key, value_json, source, observed_at, expires_at,
                       confidence
                FROM world_facts
                WHERE session_id IN (?, '*') AND expires_at >= ?
                ORDER BY observed_at DESC LIMIT ?
                """,
                (session, now, safe_limit),
            ).fetchall()
        decoded: list[WorldFact] = []
        for row in rows:
            try:
                value = json.loads(row["value_json"])
            except (TypeError, ValueError):
                continue
            decoded.append(
                WorldFact(
                    key=row["fact_key"],
                    value=value,
                    source=row["source"],
                    observed_at=float(row["observed_at"]),
                    expires_at=float(row["expires_at"]),
                    confidence=float(row["confidence"]),
                    session_id=row["session_id"],
                )
            )
        return tuple(decoded)

    def planner_context(self, session_id: str, *, limit: int = 8) -> tuple[dict[str, str], ...]:
        context: list[dict[str, str]] = []
        for fact in reversed(self.facts(session_id, limit=limit)):
            age = max(0, int(time.time() - fact.observed_at))
            value = json.dumps(fact.value, ensure_ascii=False, separators=(",", ":"))[:1_200]
            context.append(
                {
                    "request": "verified-world-state",
                    "action": fact.key,
                    "outcome": (
                        f"source={fact.source}; age_seconds={age}; "
                        f"confidence={fact.confidence:.2f}; value={value}"
                    ),
                }
            )
        return tuple(context)

    def save_goal(self, goal: StoredGoal) -> None:
        validated = self._validate_goal(goal)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_goals
                    (session_id, original_request, remaining_rounds, remaining_actions,
                     continue_after_current, remote, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    original_request=excluded.original_request,
                    remaining_rounds=excluded.remaining_rounds,
                    remaining_actions=excluded.remaining_actions,
                    continue_after_current=excluded.continue_after_current,
                    remote=excluded.remote,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                (
                    validated.session_id,
                    validated.original_request,
                    validated.remaining_rounds,
                    validated.remaining_actions,
                    int(validated.continue_after_current),
                    int(validated.remote),
                    validated.created_at,
                    validated.updated_at,
                ),
            )
            connection.execute(
                """
                DELETE FROM agent_goals WHERE rowid IN (
                    SELECT rowid FROM agent_goals
                    ORDER BY updated_at DESC LIMIT -1 OFFSET ?
                )
                """,
                (self._MAX_GOALS,),
            )

    def _validate_goal(self, goal: StoredGoal) -> StoredGoal:
        session = self._clean_identifier(goal.session_id, 128)
        request = goal.original_request.strip()[:1_000]
        if not request or "\x00" in request:
            raise ValueError("Solicitud de objetivo inválida")
        for name, value, maximum in (
            ("rondas", goal.remaining_rounds, self._MAX_GOAL_ROUNDS),
            ("acciones", goal.remaining_actions, self._MAX_GOAL_ACTIONS),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                raise ValueError(f"Límite de {name} inválido")
        if not isinstance(goal.continue_after_current, bool) or not isinstance(goal.remote, bool):
            raise ValueError("Banderas de objetivo inválidas")
        if not all(
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
            for value in (goal.created_at, goal.updated_at)
        ):
            raise ValueError("Fecha de objetivo inválida")
        if goal.updated_at < goal.created_at:
            raise ValueError("Cronología de objetivo inválida")
        return StoredGoal(
            session_id=session,
            original_request=request,
            remaining_rounds=goal.remaining_rounds,
            remaining_actions=goal.remaining_actions,
            continue_after_current=goal.continue_after_current,
            remote=goal.remote,
            created_at=float(goal.created_at),
            updated_at=float(goal.updated_at),
        )

    def load_goal(self, session_id: str, *, max_age_seconds: float) -> StoredGoal | None:
        session = self._clean_identifier(session_id, 128)
        if (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, int | float)
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            raise ValueError("Antigüedad máxima inválida")
        cutoff = time.time() - max_age_seconds
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_goals WHERE session_id = ? AND updated_at >= ?",
                (session, cutoff),
            ).fetchone()
            connection.execute("DELETE FROM agent_goals WHERE updated_at < ?", (cutoff,))
        if row is None:
            return None
        try:
            if row["continue_after_current"] not in (0, 1) or row["remote"] not in (0, 1):
                raise ValueError("Banderas persistidas inválidas")
            return self._validate_goal(
                StoredGoal(
                    session_id=row["session_id"],
                    original_request=row["original_request"],
                    remaining_rounds=int(row["remaining_rounds"]),
                    remaining_actions=int(row["remaining_actions"]),
                    continue_after_current=bool(row["continue_after_current"]),
                    remote=bool(row["remote"]),
                    created_at=float(row["created_at"]),
                    updated_at=float(row["updated_at"]),
                )
            )
        except (TypeError, ValueError):
            self.delete_goal(session)
            return None

    def delete_goal(self, session_id: str) -> None:
        session = self._clean_identifier(session_id, 128)
        with self._connect() as connection:
            connection.execute("DELETE FROM agent_goals WHERE session_id = ?", (session,))

    def clear_session(self, session_id: str) -> None:
        session = self._clean_identifier(session_id, 128)
        with self._connect() as connection:
            connection.execute("DELETE FROM agent_goals WHERE session_id = ?", (session,))
            connection.execute("DELETE FROM world_facts WHERE session_id = ?", (session,))
