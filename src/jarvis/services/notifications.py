from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path


class NotificationStore:
    """Durable outbox with idempotent publication and explicit delivery acknowledgement."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, payload TEXT NOT NULL,
                created REAL NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0)""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS notification_sessions "
                "(session TEXT PRIMARY KEY, last_seen REAL NOT NULL)"
            )
        db.close()

    def register(self, session: str) -> None:
        db = self.connect()
        try:
            with db:
                db.execute(
                    "INSERT INTO notification_sessions VALUES (?, ?) "
                    "ON CONFLICT(session) DO UPDATE SET last_seen=excluded.last_seen",
                    (session, time.time()),
                )
                db.execute(
                    "DELETE FROM notification_sessions WHERE last_seen < ?",
                    (time.time() - 7 * 86400,),
                )
        finally:
            db.close()

    def sessions(self) -> list[str]:
        db = self.connect()
        try:
            return [
                r[0]
                for r in db.execute(
                    "SELECT session FROM notification_sessions ORDER BY last_seen DESC LIMIT 64"
                )
            ]
        finally:
            db.close()

    def has_event(self, session: str, event_id: str) -> bool:
        db = self.connect()
        try:
            return any(
                json.loads(r[0]).get("id") == event_id
                for r in db.execute("SELECT payload FROM notifications WHERE session=?", (session,))
            )
        finally:
            db.close()

    def connect(self):
        return sqlite3.connect(self.path, timeout=3)

    def publish(self, session: str, payload: dict) -> dict:
        key = f"{session}:{payload.get('event')}:{payload.get('id')}:{payload.get('due_at')}"
        identifier = hashlib.sha256(key.encode()).hexdigest()[:32]
        item = {**payload, "notification_id": identifier}
        db = self.connect()
        try:
            with db:
                db.execute(
                    "INSERT OR IGNORE INTO notifications VALUES (?, ?, ?, ?, 0)",
                    (identifier, session, json.dumps(item), time.time()),
                )
                db.execute(
                    "DELETE FROM notifications WHERE created < ?", (time.time() - 30 * 86400,)
                )
        finally:
            db.close()
        return item

    def pending(self, session: str, *, after: float = 0, offset: int = 0) -> list[dict]:
        db = self.connect()
        try:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM notifications WHERE session=? AND acknowledged=0 "
                    "AND created>=? ORDER BY created,id LIMIT 100 OFFSET ?",
                    (session, after, offset),
                )
            ]
        finally:
            db.close()

    def acknowledge(self, session: str, identifiers: list[str]) -> None:
        db = self.connect()
        try:
            with db:
                db.executemany(
                    "UPDATE notifications SET acknowledged=1 WHERE session=? AND id=?",
                    [(session, identifier) for identifier in identifiers[:100]],
                )
        finally:
            db.close()
