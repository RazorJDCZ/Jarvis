from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class FeedbackStore:
    """Small local eval inbox; it never sends feedback outside this computer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=4.0)
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
                    category TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(trace_id, session_id)
                )
                """
            )

    def record(
        self,
        trace_id: str,
        session_id: str,
        rating: int,
        *,
        category: str = "general",
        note: str = "",
    ) -> None:
        if rating not in {-1, 1}:
            raise ValueError("Calificación inválida")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_feedback
                    (trace_id, session_id, rating, category, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id, session_id) DO UPDATE SET
                    rating=excluded.rating,
                    category=excluded.category,
                    note=excluded.note,
                    created_at=excluded.created_at
                """,
                (
                    trace_id[:64],
                    session_id[:128],
                    rating,
                    category.strip()[:40] or "general",
                    note.strip()[:500],
                    time.time(),
                ),
            )
            connection.execute(
                """
                DELETE FROM agent_feedback WHERE id IN (
                    SELECT id FROM agent_feedback ORDER BY created_at DESC LIMIT -1 OFFSET 5000
                )
                """
            )
