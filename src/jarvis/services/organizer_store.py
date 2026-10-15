"""Small durable records for the personal organizer; no provider credentials here."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager


class OrganizerStore:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(kind TEXT, id TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,id))"
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, kind, key, default=None):
        with self.db() as db:
            row = db.execute(
                "SELECT value FROM records WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, key, value):
        with self.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, key, json.dumps(value))
            )
        return value

    def list(self, kind):
        with self.db() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT value FROM records WHERE kind=? ORDER BY rowid DESC LIMIT 2000", (kind,)
                )
            ]

    def delete(self, kind, key):
        with self.db() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))

    def replace(self, kind, entries):
        with self.db() as db:
            db.execute("DELETE FROM records WHERE kind=?", (kind,))
            db.executemany(
                "INSERT INTO records VALUES (?,?,?)",
                [(kind, key, json.dumps(value)) for key, value in entries.items()],
            )

    def seen(self, key, seconds):
        previous = self.get("throttle", key, 0)
        return time.time() - previous < seconds
