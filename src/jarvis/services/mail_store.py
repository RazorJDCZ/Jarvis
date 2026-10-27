"""Local mail cache. Credentials are encrypted for the current Windows user with DPAPI."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_SEARCH_FILLERS = frozenset(
    {
        "a",
        "acerca",
        "al",
        "algun",
        "algunos",
        "correo",
        "correos",
        "cuales",
        "de",
        "del",
        "dime",
        "el",
        "email",
        "emails",
        "en",
        "han",
        "llegado",
        "llegaron",
        "la",
        "las",
        "lo",
        "los",
        "mail",
        "mails",
        "me",
        "mis",
        "muestra",
        "relacionado",
        "relacionados",
        "por",
        "que",
        "se",
        "sobre",
        "tema",
        "tematica",
        "tengo",
        "un",
        "una",
        "unas",
        "unos",
    }
)
_TOPIC_GROUPS = (
    frozenset(
        {
            "academico",
            "asignatura",
            "campus",
            "clase",
            "curso",
            "deber",
            "docente",
            "entrega",
            "estudio",
            "examen",
            "informe",
            "moodle",
            "profesor",
            "tarea",
            "universidad",
        }
    ),
    frozenset(
        {
            "banco",
            "cobro",
            "factura",
            "finanza",
            "pago",
            "recibo",
            "tarjeta",
            "transferencia",
        }
    ),
    frozenset(
        {
            "acceso",
            "alerta",
            "contrasena",
            "cuenta",
            "inicio",
            "login",
            "seguridad",
            "sesion",
            "verificacion",
        }
    ),
    frozenset(
        {
            "compra",
            "envio",
            "orden",
            "paquete",
            "pedido",
            "producto",
            "tienda",
        }
    ),
    frozenset(
        {
            "avion",
            "hotel",
            "reserva",
            "turismo",
            "viaje",
            "vuelo",
        }
    ),
    frozenset(
        {
            "cita",
            "clinica",
            "doctor",
            "medico",
            "salud",
        }
    ),
)


def _search_normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9@._+-]+", " ", text).strip()


def _search_tokens(value: object) -> tuple[str, ...]:
    return tuple(token for token in _search_normalized(value).split() if token)


def _stem(value: str) -> str:
    for suffix in ("mente", "aciones", "acion", "idades", "idad", "es", "os", "as", "s"):
        if len(value) - len(suffix) >= 4 and value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _contains_term(term: str, tokens: tuple[str, ...], normalized: str) -> bool:
    if term in tokens or (len(term) >= 4 and term in normalized):
        return True
    target = _stem(term)
    return len(target) >= 4 and any(_stem(token) == target for token in tokens)


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
                CREATE TABLE IF NOT EXISTS mail_messages (
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL, version TEXT NOT NULL,
                    subject TEXT NOT NULL, sender TEXT NOT NULL,
                    received TEXT NOT NULL, url TEXT NOT NULL,
                    body TEXT NOT NULL, message_id TEXT NOT NULL DEFAULT '',
                    UNIQUE(account_id, version));
                CREATE INDEX IF NOT EXISTS mail_messages_received
                    ON mail_messages(received DESC);
            """)
            self._ensure_column(db, "mail", "message_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "reply_to", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "sent_version", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "mail", "sent_at", "REAL NOT NULL DEFAULT 0")
            # Older Jarvis versions only retained the newest message in each conversation.
            # Seed the immutable archive in one transaction. A bounded Gmail rebuild can then
            # recover the remaining messages without changing the user's review state.
            db.execute(
                "INSERT OR IGNORE INTO mail_messages "
                "(id,account_id,thread_id,version,subject,sender,received,url,body,message_id) "
                "SELECT 'legacy:'||account_id||':'||version,account_id,thread_id,version,"
                "subject,sender,received,url,substr(body,1,30000),message_id FROM mail"
            )

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
            db.execute("DELETE FROM mail_messages WHERE account_id=?", (identifier,))
            db.execute(
                "DELETE FROM mail_tasks WHERE mail_id IN (SELECT id FROM mail WHERE account_id=?)",
                (identifier,),
            )
            db.execute("DELETE FROM mail WHERE account_id=?", (identifier,))
            db.execute("DELETE FROM accounts WHERE id=?", (identifier,))

    def archive(self, account_id, message):
        """Retain one immutable local copy per provider message for derived private views."""

        version = str(message.get("version") or "").strip()
        if not version:
            return False
        identifier = hashlib.sha256(f"{account_id}:{version}".encode()).hexdigest()[:32]
        fields = (
            "thread_id",
            "version",
            "subject",
            "sender",
            "received",
            "url",
            "body",
            "message_id",
        )
        values = [str(message.get(field) or "") for field in fields]
        values[6] = values[6][:30_000]
        with self.db() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO mail_messages "
                "(id,account_id,thread_id,version,subject,sender,received,url,body,message_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (identifier, account_id, *values),
            )
        return bool(cursor.rowcount)

    def archived_messages(self, *, since="", until="", limit=5000):
        safe_limit = max(1, min(int(limit), 10_000))
        clauses = []
        values: list[object] = []
        if since:
            clauses.append("mm.received>=?")
            values.append(since)
        if until:
            clauses.append("mm.received<?")
            values.append(until)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.db() as db:
            rows = db.execute(
                "SELECT mm.*,a.email,a.provider FROM mail_messages mm JOIN accounts a "
                "ON mm.account_id=a.id"
                + where
                + " ORDER BY mm.received DESC LIMIT ?",
                (*values, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def archive_coverage(self):
        with self.db() as db:
            rows = db.execute(
                "SELECT a.email,a.provider,MIN(mm.received) AS first_message,"
                "MAX(mm.received) AS last_message,COUNT(mm.id) AS messages "
                "FROM accounts a LEFT JOIN mail_messages mm ON mm.account_id=a.id "
                "GROUP BY a.id ORDER BY a.email"
            ).fetchall()
        return [dict(row) for row in rows]

    def reset_google_sync(self):
        """Schedule a bounded 30-day rebuild using the existing paginated Gmail worker."""

        with self.db() as db:
            identifiers = [
                row[0] for row in db.execute("SELECT id FROM accounts WHERE provider='google'")
            ]
            if identifiers:
                db.execute("DELETE FROM mail_sync")
                db.execute("UPDATE accounts SET synced=0,error='' WHERE provider='google'")
        return identifiers

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
        self.archive(account_id, message)
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

    def _literal_search(self, query: str, *, limit: int = 20, include_resolved: bool = True):
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

    def search(self, query: str, *, limit: int = 20, include_resolved: bool = True):
        """Rank broad local matches by meaning, field quality, priority and recency."""

        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("La búsqueda debe contener entre 1 y 300 caracteres")
        safe_limit = max(1, min(int(limit), 50))
        normalized_query = _search_normalized(query)
        sort = "relevance"
        if re.search(r"\b(?:mas recientes?|ultimos?|por fecha|nuevos?)\b", normalized_query):
            sort = "newest"
        elif re.search(r"\b(?:mas importantes?|prioridad|urgentes?)\b", normalized_query):
            sort = "importance"
        cleaned_query = re.sub(
            r"\b(?:subject|asunto|sender|remitente|from)\s*:\s*",
            " ",
            normalized_query,
            flags=re.IGNORECASE,
        )
        cleaned_query = re.sub(
            r"(?i)\b(?:ordenados? por )?(?:relevancia|mas recientes?|ultimos?|por fecha|"
            r"nuevos?|mas importantes?|prioridad|urgentes?)\b",
            " ",
            cleaned_query,
        )
        core_terms = tuple(
            dict.fromkeys(
                token
                for token in _search_tokens(cleaned_query)[:16]
                if token not in _SEARCH_FILLERS
            )
        )
        if not core_terms:
            # Literal punctuation searches such as "%" are valid but cannot match safely.
            return []
        phrase = " ".join(core_terms)
        expanded: set[str] = set()
        for group in _TOPIC_GROUPS:
            stems = {_stem(candidate) for candidate in group}
            if any(_stem(term) in stems for term in core_terms):
                expanded.update(group)
        expanded.difference_update(core_terms)

        where = "" if include_resolved else "WHERE m.state!='resolved'"
        with self.db() as db:
            rows = db.execute(
                "SELECT m.*,a.email,a.provider FROM mail m JOIN accounts a "
                f"ON m.account_id=a.id {where} ORDER BY m.received DESC LIMIT 2500"
            ).fetchall()

        ranked: list[tuple[tuple[float, float, float], dict[str, object]]] = []
        now = time.time()
        for row in rows:
            item = dict(row)
            fields = {
                "subject": _search_normalized(item.get("subject")),
                "sender": _search_normalized(item.get("sender")),
                "summary": _search_normalized(item.get("summary")),
                "body": _search_normalized(item.get("body")),
                "account": _search_normalized(item.get("email")),
            }
            field_tokens = {name: tuple(value.split()) for name, value in fields.items()}
            weights = {
                "subject": 9.0,
                "sender": 10.0,
                "summary": 6.0,
                "body": 2.5,
                "account": 4.0,
            }
            matched_core: set[str] = set()
            reasons: list[str] = []
            score = 0.0
            for field, value in fields.items():
                matches = {
                    term
                    for term in core_terms
                    if _contains_term(term, field_tokens[field], value)
                }
                if matches:
                    matched_core.update(matches)
                    score += len(matches) * weights[field]
                    reasons.append(field)
            topic_hits = {
                term
                for term in expanded
                if any(
                    _contains_term(term, field_tokens[field], fields[field])
                    for field in ("subject", "summary", "body")
                )
            }
            if not matched_core and not topic_hits:
                continue
            score += min(8.0, len(topic_hits) * 0.9)
            coverage = len(matched_core) / len(core_terms)
            score += coverage * 12
            if phrase:
                if phrase in fields["subject"]:
                    score += 24
                elif phrase in fields["sender"]:
                    score += 18
                elif phrase in fields["summary"]:
                    score += 14
                elif phrase in fields["body"]:
                    score += 8
            priority_rank = {"high": 3.0, "normal": 1.0, "low": 0.0}.get(
                str(item.get("priority", "normal")), 1.0
            )
            score += priority_rank
            if item.get("state") != "resolved":
                score += 0.5
            try:
                received = datetime.fromisoformat(
                    str(item.get("received", "")).replace("Z", "+00:00")
                )
                if received.tzinfo is None:
                    received = received.replace(tzinfo=UTC)
                received_timestamp = received.timestamp()
            except (TypeError, ValueError):
                received_timestamp = 0.0
            age_days = (
                max(0.0, (now - received_timestamp) / 86_400)
                if received_timestamp
                else 3650
            )
            score += max(0.0, 3.0 - age_days / 30.0)
            public = {key: value for key, value in item.items() if key != "body"}
            public["relevance"] = round(score, 2)
            public["matched_terms"] = sorted(matched_core)
            public["topic_matches"] = sorted(topic_hits)[:8]
            public["match_fields"] = reasons
            if sort == "newest":
                rank = (received_timestamp, score, priority_rank)
            elif sort == "importance":
                rank = (priority_rank, score, received_timestamp)
            else:
                rank = (score, priority_rank, received_timestamp)
            ranked.append((rank, public))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _rank, item in ranked[:safe_limit]]

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
