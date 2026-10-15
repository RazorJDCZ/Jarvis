"""Local mail cache. Credentials are encrypted for the current Windows user with DPAPI."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("El almacén de credenciales requiere Windows DPAPI")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(Blob),
    ]
    function.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError("No se pudo acceder al almacén cifrado de Windows")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class MailStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, email TEXT NOT NULL,
                    synced REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS mail (
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL, thread_id TEXT NOT NULL,
                    version TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
                    received TEXT NOT NULL, url TEXT NOT NULL, body TEXT NOT NULL,
                    summary TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal',
                    reason TEXT NOT NULL DEFAULT '', deadline TEXT NOT NULL DEFAULT '',
                    summary_kind TEXT NOT NULL DEFAULT 'extract',
                    state TEXT NOT NULL DEFAULT 'review', snoozed_until REAL NOT NULL DEFAULT 0,
                    task_id TEXT NOT NULL DEFAULT '', draft TEXT NOT NULL DEFAULT '',
                    message_id TEXT NOT NULL DEFAULT '', reply_to TEXT NOT NULL DEFAULT '',
                    sent_version TEXT NOT NULL DEFAULT '', sent_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(account_id, thread_id));
                CREATE INDEX IF NOT EXISTS mail_received ON mail(received DESC);
                CREATE TABLE IF NOT EXISTS mail_tasks (
                    mail_id TEXT PRIMARY KEY, request_key TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mail_sync (
                    account_id TEXT PRIMARY KEY, since REAL NOT NULL,
                    page_token TEXT NOT NULL, started REAL NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0);
            """)
            self._ensure_column(db, "mail", "message_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "reply_to", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "sent_version", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "sent_at", "REAL NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column(db, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def secret(self, key: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT value FROM secrets WHERE key=?", (key,)).fetchone()
        return json.loads(protect(row[0], True)) if row else {}

    def save_secret(self, key: str, value: dict):
        encrypted = protect(json.dumps(value).encode())
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO secrets VALUES (?,?)", (key, encrypted))

    def accounts(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY email")]

    def connect(self, provider, email, tokens):
        identifier = hashlib.sha256(f"{provider}:{email.lower()}".encode()).hexdigest()[:32]
        self.save_secret(identifier, tokens)
        with self.db() as db:
            db.execute(
                "INSERT INTO accounts(id,provider,email) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET error=''",
                (identifier, provider, email),
            )
        return identifier

    def disconnect(self, identifier):
        with self.db() as db:
            db.execute("DELETE FROM secrets WHERE key=?", (identifier,))
            db.execute("DELETE FROM mail_sync WHERE account_id=?", (identifier,))
            db.execute(
                "DELETE FROM mail_tasks WHERE mail_id IN (SELECT id FROM mail WHERE account_id=?)",
                (identifier,),
            )
            db.execute("DELETE FROM mail WHERE account_id=?", (identifier,))
            db.execute("DELETE FROM accounts WHERE id=?", (identifier,))

    def account_result(self, identifier, *, synced=None, error=""):
        with self.db() as db:
            db.execute(
                "UPDATE accounts SET synced=COALESCE(?,synced),error=? WHERE id=?",
                (synced, error, identifier),
            )

    def sync_progress(self, identifier):
        with self.db() as db:
            row = db.execute(
                "SELECT since,page_token,started,processed FROM mail_sync WHERE account_id=?",
                (identifier,),
            ).fetchone()
        return dict(row) if row else None

    def save_sync_progress(self, identifier, *, since, page_token, started, processed):
        with self.db() as db:
            db.execute(
                "INSERT INTO mail_sync(account_id,since,page_token,started,processed) "
                "VALUES (?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                "since=excluded.since,page_token=excluded.page_token,"
                "started=excluded.started,processed=excluded.processed",
                (identifier, since, page_token, started, processed),
            )

    def clear_sync_progress(self, identifier):
        with self.db() as db:
            db.execute("DELETE FROM mail_sync WHERE account_id=?", (identifier,))

    def task_request(self, identifier, payload):
        # Persist both key and exact body before network I/O, including across restarts.
        with self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO mail_tasks VALUES (?,?,?)",
                (identifier, "mail-" + uuid4().hex, json.dumps(payload)),
            )
            row = db.execute("SELECT * FROM mail_tasks WHERE mail_id=?", (identifier,)).fetchone()
            return row["request_key"], json.loads(row["payload"])

    def get(self, identifier):
        with self.db() as db:
            row = db.execute(
                "SELECT m.*,a.email,a.provider FROM mail m JOIN accounts a "
                "ON m.account_id=a.id WHERE m.id=?",
                (identifier,),
            ).fetchone()
        return dict(row) if row else None

    def ingest(self, account_id, message):
        identifier = hashlib.sha256(f"{account_id}:{message['thread_id']}".encode()).hexdigest()[
            :32
        ]
        old = self.get(identifier)
        if old and (old["received"], old["version"]) == (message["received"], message["version"]):
            return False
        if old and old["received"] > message["received"]:
            return False
        keys = (
            "thread_id",
            "version",
            "subject",
            "sender",
            "received",
            "url",
            "body",
            "message_id",
            "reply_to",
        )
        with self.db() as db:
            db.execute(
                """INSERT INTO mail
                (id,account_id,thread_id,version,subject,sender,received,url,body,summary,
                 message_id,reply_to)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                version=excluded.version,subject=excluded.subject,sender=excluded.sender,
                received=excluded.received,url=excluded.url,body=excluded.body,
                message_id=excluded.message_id,reply_to=excluded.reply_to,
                summary=excluded.summary,summary_kind='extract',priority='normal',reason='',
                deadline='',draft='',state='review',snoozed_until=0""",
                (
                    identifier,
                    account_id,
                    *(message.get(k, "") for k in keys[:7]),
                    message["body"][:700],
                    message.get("message_id", ""),
                    message.get("reply_to", ""),
                ),
            )
        return True

    def list(self, include_resolved=False):
        with self.db() as db:
            rows = db.execute(
                "SELECT m.*,a.email,a.provider FROM mail m JOIN accounts a "
                "ON m.account_id=a.id "
                "WHERE (? OR (state!='resolved' AND snoozed_until<=?)) "
                "ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END,received DESC "
                "LIMIT 500",
                (include_resolved, time.time()),
            )
            return [{k: v for k, v in dict(r).items() if k != "body"} for r in rows]

    def search(self, query: str, *, limit: int = 20, include_resolved: bool = True):
        words = [word.casefold() for word in query.split() if word.strip()]
        if not words or len(query) > 300:
            raise ValueError("La búsqueda debe contener entre 1 y 300 caracteres")
        safe_limit = max(1, min(int(limit), 50))
        clauses = []
        values: list[object] = []
        for word in words[:8]:
            clauses.append(
                "(LOWER(m.subject) LIKE ? ESCAPE '\\' OR "
                "LOWER(m.sender) LIKE ? ESCAPE '\\' OR "
                "LOWER(m.summary) LIKE ? ESCAPE '\\' OR "
                "LOWER(m.body) LIKE ? ESCAPE '\\' OR "
                "LOWER(a.email) LIKE ? ESCAPE '\\')"
            )
            pattern = "%" + word.replace("%", "\\%").replace("_", "\\_") + "%"
            values.extend([pattern] * 5)
        resolved = "" if include_resolved else "AND m.state!='resolved'"
        with self.db() as db:
            rows = db.execute(
                "SELECT m.*,a.email,a.provider FROM mail m JOIN accounts a "
                "ON m.account_id=a.id WHERE "
                + " AND ".join(clauses)
                + " "
                + resolved
                + " ORDER BY CASE m.priority WHEN 'high' THEN 0 ELSE 1 END,m.received DESC "
                "LIMIT ?",
                (*values, safe_limit),
            ).fetchall()
        return [{k: v for k, v in dict(row).items() if k != "body"} for row in rows]

    def update(self, identifier, **values):
        allowed = {
            "state",
            "snoozed_until",
            "summary",
            "priority",
            "reason",
            "deadline",
            "summary_kind",
            "draft",
            "task_id",
            "sent_version",
            "sent_at",
        }
        if not values or set(values) - allowed:
            raise ValueError("Campos de correo inválidos")
        with self.db() as db:
            db.execute(
                "UPDATE mail SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), identifier),
            )

    def pending_summaries(self, retry_failed=False):
        with self.db() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM mail WHERE summary_kind='extract' "
                    "OR (? AND summary_kind='extract_failed') ORDER BY received DESC LIMIT 3",
                    (retry_failed,),
                )
            ]
