from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.config import Settings
from jarvis.schemas import ProviderStatus


def normalize_memory_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(without_accents.split())


def _clean_text(value: str, maximum: int) -> str:
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split())[:maximum].strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _third_person_possessive(value: str) -> str:
    converted = re.sub(r"^mis\b", "sus", value, flags=re.IGNORECASE)
    return re.sub(r"^mi\b", "su", converted, flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    memory_key: str
    content: str
    category: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    memory_key: str
    content: str
    category: str
    explicit: bool = False


@dataclass(frozen=True, slots=True)
class MemoryStats:
    memories: int
    sessions: int
    turns: int


class MemoryExtractor:
    _EXPLICIT = re.compile(
        r"^\s*(?:jarvis[\s,;:]+)?(?:"
        r"recuerda|recu[eé]rdame|no olvides|quiero que recuerdes|"
        r"guarda en tu memoria|anota en tu memoria"
        r")(?:\s+por favor)?\s+que\s+(.+?)\s*[.!?]*$",
        flags=re.IGNORECASE,
    )
    _QUESTION_STARTS = (
        "que ",
        "quien ",
        "como ",
        "donde ",
        "cuando ",
        "cual ",
        "puedes ",
        "podrias ",
        "sabes ",
    )
    _SENSITIVE_MARKERS = (
        "contrasena",
        "password",
        "codigo de acceso",
        "codigo de verificacion",
        "token",
        "api key",
        "clave api",
        "clave privada",
        "private key",
        "frase semilla",
        "seed phrase",
        "numero de tarjeta",
        "tarjeta de credito",
        "tarjeta de debito",
        "cvv",
        "pin bancario",
    )
    _IMPLICIT_PATTERNS = (
        (
            re.compile(r"^\s*(?:yo\s+)?vivo\s+en\s+(.+?)\s*[.!]*$", re.IGNORECASE),
            "location:home",
            "ubicacion",
            "Vive en {value}.",
        ),
        (
            re.compile(r"^\s*(?:yo\s+)?estudio\s+(.+?)\s*[.!]*$", re.IGNORECASE),
            "education:study",
            "estudios",
            "Estudia {value}.",
        ),
        (
            re.compile(r"^\s*(?:yo\s+)?trabajo\s+como\s+(.+?)\s*[.!]*$", re.IGNORECASE),
            "work:role",
            "trabajo",
            "Trabaja como {value}.",
        ),
        (
            re.compile(r"^\s*(?:yo\s+)?trabajo\s+en\s+(.+?)\s*[.!]*$", re.IGNORECASE),
            "work:place",
            "trabajo",
            "Trabaja en {value}.",
        ),
    )
    _PERSONAL_FACT = re.compile(
        r"^\s*mi\s+(.{2,80}?)\s+(?:es|se llama)\s+(.{1,300}?)\s*[.!]*$",
        flags=re.IGNORECASE,
    )
    _LIKES = re.compile(r"^\s*(?:a m[ií]\s+)?me\s+gustan?\s+(.+?)\s*[.!]*$", re.IGNORECASE)
    _DISLIKES = re.compile(
        r"^\s*(?:a m[ií]\s+)?no\s+me\s+gustan?\s+(.+?)\s*[.!]*$",
        re.IGNORECASE,
    )
    _PREFERS = re.compile(r"^\s*(?:yo\s+)?prefiero\s+(.+?)\s*[.!]*$", re.IGNORECASE)
    _GOALS = re.compile(
        r"^\s*(?:yo\s+)?quiero\s+(aprender|crear|hacer|lograr|mejorar|terminar)\s+"
        r"(.+?)\s*[.!]*$",
        re.IGNORECASE,
    )
    _PROJECT = re.compile(
        r"^\s*(?:yo\s+)?estoy\s+(?:trabajando|creando|desarrollando)\s+"
        r"(?:en\s+)?(.+?)\s*[.!]*$",
        re.IGNORECASE,
    )

    @classmethod
    def contains_sensitive_data(cls, text: str) -> bool:
        normalized = normalize_memory_text(text)
        return any(marker in normalized for marker in cls._SENSITIVE_MARKERS)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(normalize_memory_text(value).encode("utf-8")).hexdigest()[:16]

    @classmethod
    def explicit_candidate(cls, message: str) -> MemoryCandidate | None:
        match = cls._EXPLICIT.fullmatch(message)
        if match is None:
            return None
        content = _clean_text(match.group(1), 500)
        if not content or cls.contains_sensitive_data(content):
            return None
        personal = cls._PERSONAL_FACT.fullmatch(content)
        if personal is not None:
            raw_subject = _clean_text(personal.group(1), 80)
            value = _clean_text(personal.group(2), 300).rstrip(".")
            subject = normalize_memory_text(raw_subject)[:80]
            key = f"personal:{subject}"
            category = "dato_personal"
            content = f"Su {raw_subject} es {_third_person_possessive(value)}."
        else:
            key = f"explicit:{cls._digest(content)}"
            category = "explicito"
        return MemoryCandidate(key, content.rstrip(".") + ".", category, explicit=True)

    @classmethod
    def is_explicit_request(cls, message: str) -> bool:
        return cls._EXPLICIT.fullmatch(message) is not None

    @classmethod
    def implicit_candidate(cls, message: str) -> MemoryCandidate | None:
        clean = _clean_text(message, 1_000)
        normalized = normalize_memory_text(clean).lstrip("¿¡")
        if (
            not clean
            or "?" in clean
            or any(normalized.startswith(start) for start in cls._QUESTION_STARTS)
            or cls.contains_sensitive_data(clean)
        ):
            return None

        for pattern, key, category, template in cls._IMPLICIT_PATTERNS:
            match = pattern.fullmatch(clean)
            if match is not None:
                value = _third_person_possessive(_clean_text(match.group(1), 300).rstrip("."))
                return MemoryCandidate(key, template.format(value=value), category)

        personal = cls._PERSONAL_FACT.fullmatch(clean)
        if personal is not None:
            subject = _clean_text(personal.group(1), 80)
            value = _third_person_possessive(_clean_text(personal.group(2), 300).rstrip("."))
            return MemoryCandidate(
                f"personal:{normalize_memory_text(subject)}",
                f"Su {subject} es {value}.",
                "dato_personal",
            )

        for pattern, prefix, category, template in (
            (cls._LIKES, "like", "preferencia", "Le gusta {value}."),
            (cls._DISLIKES, "dislike", "preferencia", "No le gusta {value}."),
            (cls._PREFERS, "prefer", "preferencia", "Prefiere {value}."),
        ):
            match = pattern.fullmatch(clean)
            if match is not None:
                value = _third_person_possessive(_clean_text(match.group(1), 300).rstrip("."))
                key = f"preference:{prefix}:{cls._digest(value)}"
                return MemoryCandidate(key, template.format(value=value), category)

        goal = cls._GOALS.fullmatch(clean)
        if goal is not None:
            action = _clean_text(goal.group(1), 30).casefold()
            value = _third_person_possessive(_clean_text(goal.group(2), 300).rstrip("."))
            content = f"Quiere {action} {value}."
            return MemoryCandidate(
                f"goal:{cls._digest(content)}",
                content,
                "objetivo",
            )

        project = cls._PROJECT.fullmatch(clean)
        if project is not None:
            value = _third_person_possessive(_clean_text(project.group(1), 300).rstrip("."))
            return MemoryCandidate(
                f"project:{cls._digest(value)}",
                f"Está trabajando en {value}.",
                "proyecto",
            )
        return None


class MemoryStore:
    _STOP_WORDS = frozenset(
        {
            "algo",
            "analisis",
            "analiza",
            "analizar",
            "como",
            "con",
            "cuentame",
            "cual",
            "cuando",
            "describe",
            "descripcion",
            "dime",
            "donde",
            "ella",
            "este",
            "esta",
            "esto",
            "hablemos",
            "opina",
            "opinas",
            "para",
            "personalidad",
            "pero",
            "piensa",
            "piensas",
            "porque",
            "que",
            "quien",
            "sobre",
            "tengo",
            "tiene",
            "una",
            "unos",
            "unas",
        }
    )

    def __init__(
        self,
        path: Path,
        enabled: bool = True,
        max_entries: int = 500,
        max_turns: int = 60,
        retention_days: int = 30,
    ) -> None:
        self.path = path
        self.enabled = enabled
        self.max_entries = max(10, min(max_entries, 5_000))
        self.max_turns = max(0, min(max_turns, 500))
        self.retention_days = max(1, min(retention_days, 365))
        self.available = False
        self.error = "Memoria desactivada"
        self._lock = threading.RLock()
        if enabled:
            self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA secure_delete = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY,
                        memory_key TEXT NOT NULL UNIQUE,
                        content TEXT NOT NULL,
                        normalized_content TEXT NOT NULL,
                        category TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memories_category_updated
                        ON memories(category, updated_at DESC);
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id INTEGER PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_text TEXT NOT NULL,
                        assistant_text TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_turns_session_created
                        ON conversation_turns(session_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_turns_created
                        ON conversation_turns(created_at DESC);
                    PRAGMA user_version = 1;
                    """
                )
            self.available = True
            self.error = ""
        except (OSError, sqlite3.Error) as exc:
            self.available = False
            self.error = str(exc)[:300]

    @staticmethod
    def _entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            memory_key=str(row["memory_key"]),
            content=str(row["content"]),
            category=str(row["category"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def upsert(self, candidate: MemoryCandidate) -> MemoryEntry | None:
        if not self.available:
            return None
        now = _utc_now()
        content = _clean_text(candidate.content, 500)
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO memories (
                        memory_key, content, normalized_content, category, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_key) DO UPDATE SET
                        content = excluded.content,
                        normalized_content = excluded.normalized_content,
                        category = excluded.category,
                        updated_at = excluded.updated_at
                    """,
                    (
                        candidate.memory_key,
                        content,
                        normalize_memory_text(content),
                        candidate.category,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM memories WHERE id IN (
                        SELECT id FROM memories ORDER BY updated_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.max_entries,),
                )
                row = connection.execute(
                    "SELECT * FROM memories WHERE memory_key = ?",
                    (candidate.memory_key,),
                ).fetchone()
            return self._entry(row) if row is not None else None
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return None

    def list_entries(self, limit: int = 20) -> tuple[MemoryEntry, ...]:
        if not self.available:
            return ()
        safe_limit = max(1, min(limit, 100))
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC, id DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            return tuple(self._entry(row) for row in rows)
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return ()

    @classmethod
    def _tokens(cls, value: str) -> set[str]:
        aliases = {
            "estudia": "estudio",
            "estudiar": "estudio",
            "gusta": "gusto",
            "gustan": "gusto",
            "prefiere": "preferir",
            "prefiero": "preferir",
            "trabaja": "trabajo",
            "trabajar": "trabajo",
            "quiere": "querer",
            "quiero": "querer",
            "vive": "vivir",
            "vivo": "vivir",
        }
        tokens: set[str] = set()
        for raw_token in re.findall(r"[a-z0-9]{3,}", normalize_memory_text(value)):
            if raw_token in cls._STOP_WORDS:
                continue
            token = aliases.get(raw_token, raw_token)
            if len(token) > 5 and token.endswith("es"):
                token = token[:-2]
            elif len(token) > 4 and token.endswith("s"):
                token = token[:-1]
            tokens.add(token)
        return tokens

    def relevant(self, query: str, limit: int = 8) -> tuple[MemoryEntry, ...]:
        entries = self.list_entries(self.max_entries)
        query_tokens = self._tokens(query)
        if not entries or not query_tokens:
            return ()
        normalized_query = normalize_memory_text(query)
        scored: list[tuple[float, str, MemoryEntry]] = []
        for entry in entries:
            memory_tokens = self._tokens(f"{entry.category} {entry.content}")
            overlap = query_tokens & memory_tokens
            score = float(len(overlap) * 4)
            if normalized_query in normalize_memory_text(entry.content):
                score += 4
            if score > 0:
                scored.append((score, entry.updated_at, entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        safe_limit = max(1, min(limit, 20))
        return tuple(item[2] for item in scored[:safe_limit])

    def forget_best(self, query: str) -> MemoryEntry | None:
        entries = self.list_entries(self.max_entries)
        query_tokens = self._tokens(query)
        normalized_query = normalize_memory_text(query)
        candidates: list[tuple[float, str, MemoryEntry]] = []
        for entry in entries:
            normalized_content = normalize_memory_text(entry.content)
            overlap = query_tokens & self._tokens(f"{entry.category} {entry.content}")
            score = float(len(overlap) * 4)
            if normalized_query and normalized_query in normalized_content:
                score += 8
            if score > 0:
                candidates.append((score, entry.updated_at, entry))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = candidates[0][2]
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "DELETE FROM memories WHERE memory_key = ?",
                    (selected.memory_key,),
                )
            self._compact_after_forget()
            return selected
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return None

    def add_turn(self, session_id: str, user_text: str, assistant_text: str) -> bool:
        if not self.available or self.max_turns == 0:
            return False
        user = _clean_text(user_text, 1_500)
        assistant = _clean_text(assistant_text, 2_000)
        if (
            not user
            or not assistant
            or MemoryExtractor.contains_sensitive_data(user)
            or MemoryExtractor.contains_sensitive_data(assistant)
        ):
            return False
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat(
            timespec="seconds"
        )
        try:
            with self._lock, self._connect() as connection:
                latest = connection.execute(
                    """
                    SELECT user_text, assistant_text FROM conversation_turns
                    WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (_clean_text(session_id, 128),),
                ).fetchone()
                if latest is not None and (
                    normalize_memory_text(str(latest["user_text"])) == normalize_memory_text(user)
                    and normalize_memory_text(str(latest["assistant_text"]))
                    == normalize_memory_text(assistant)
                ):
                    return False
                connection.execute(
                    """
                    INSERT INTO conversation_turns (
                        session_id, user_text, assistant_text, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (_clean_text(session_id, 128), user, assistant, _utc_now()),
                )
                connection.execute(
                    "DELETE FROM conversation_turns WHERE created_at < ?",
                    (cutoff,),
                )
                connection.execute(
                    """
                    DELETE FROM conversation_turns WHERE id IN (
                        SELECT id FROM conversation_turns ORDER BY created_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.max_turns,),
                )
            return True
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return False

    def recent_turns(
        self,
        exclude_session: str = "",
        limit: int = 3,
    ) -> tuple[tuple[str, str], ...]:
        if not self.available or self.max_turns == 0:
            return ()
        safe_limit = max(1, min(limit, 10))
        try:
            with self._lock, self._connect() as connection:
                if exclude_session:
                    rows = connection.execute(
                        """
                        SELECT user_text, assistant_text FROM conversation_turns
                        WHERE session_id != ? ORDER BY created_at DESC, id DESC LIMIT ?
                        """,
                        (exclude_session, safe_limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT user_text, assistant_text FROM conversation_turns
                        ORDER BY created_at DESC, id DESC LIMIT ?
                        """,
                        (safe_limit,),
                    ).fetchall()
            return tuple(
                (str(row["user_text"]), str(row["assistant_text"])) for row in reversed(rows)
            )
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return ()

    def clear_session(self, session_id: str) -> None:
        if not self.available:
            return
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "DELETE FROM conversation_turns WHERE session_id = ?",
                    (_clean_text(session_id, 128),),
                )
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]

    def clear_all(self) -> bool:
        if not self.available:
            return False
        try:
            with self._lock, self._connect() as connection:
                connection.execute("DELETE FROM memories")
                connection.execute("DELETE FROM conversation_turns")
            self._compact_after_forget()
            return True
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return False

    def counts(self) -> tuple[int, int]:
        stats = self.stats()
        return stats.memories, stats.turns

    def stats(self) -> MemoryStats:
        if not self.available:
            return MemoryStats(0, 0, 0)
        try:
            with self._lock, self._connect() as connection:
                memories = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS turns, COUNT(DISTINCT session_id) AS sessions
                    FROM conversation_turns
                    """
                ).fetchone()
                turns = int(row["turns"])
                sessions = int(row["sessions"])
            return MemoryStats(memories, sessions, turns)
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]
            return MemoryStats(0, 0, 0)

    def _compact_after_forget(self) -> None:
        try:
            with self._lock, self._connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
        except sqlite3.Error as exc:
            self.error = str(exc)[:300]


class MemoryService:
    _LIST_COMMANDS = (
        "que recuerdas de mi",
        "que recuerdas sobre mi",
        "dime que recuerdas de mi",
        "cuentame que recuerdas de mi",
        "que cosas recuerdas de mi",
        "muestra tus recuerdos",
        "lista tus recuerdos",
        "que tienes en tu memoria",
    )
    _CLEAR_COMMANDS = (
        "borra toda tu memoria",
        "borra todos mis recuerdos",
        "elimina todos mis recuerdos",
        "olvida todo lo que sabes de mi",
        "olvida todo sobre mi",
        "limpia toda tu memoria",
    )
    _CLEAR_CONFIRMATIONS = (
        "confirmo borrar toda mi memoria",
        "si borra toda mi memoria",
        "si elimina todos mis recuerdos",
    )
    _CANCELLATIONS = ("cancela", "cancelar", "mejor no", "no lo hagas", "no gracias")
    _FORGET_ONE = re.compile(
        r"^\s*(?:jarvis[\s,;:]+)?(?:olvida|borra de tu memoria)(?:\s+por favor)?\s+"
        r"(?:que\s+)?(.+?)\s*[.!?]*$",
        re.IGNORECASE,
    )

    def __init__(self, settings: Settings, store: MemoryStore | None = None) -> None:
        self.settings = settings
        self.store = store or MemoryStore(
            settings.memory_path,
            enabled=settings.memory_enabled,
            max_entries=settings.memory_max_entries,
            max_turns=settings.memory_max_turns,
            retention_days=settings.memory_retention_days,
        )
        self._pending_clear: dict[str, datetime] = {}
        self._pending_lock = threading.RLock()

    def status(self) -> ProviderStatus:
        if not self.settings.memory_enabled:
            return ProviderStatus(available=False, name="Memoria local", detail="Desactivada")
        if self.store.available:
            stats = self.store.stats()
            memory_label = "recuerdo" if stats.memories == 1 else "recuerdos"
            session_label = "sesión reciente" if stats.sessions == 1 else "sesiones recientes"
            turn_label = "intercambio" if stats.turns == 1 else "intercambios"
            return ProviderStatus(
                available=True,
                name="Memoria local / SQLite",
                detail=(
                    f"{stats.memories} {memory_label}; {stats.sessions} {session_label} "
                    f"con {stats.turns} {turn_label}"
                ),
            )
        return ProviderStatus(
            available=False,
            name="Memoria local",
            detail=f"No disponible: {self.store.error or 'error desconocido'}",
        )

    def is_command(self, session_id: str, message: str) -> bool:
        if not self.settings.memory_enabled:
            return False
        normalized = normalize_memory_text(message).strip("¿¡!?. ")
        if normalized in {
            "olvida esta conversacion",
            "borra la conversacion",
            "reinicia la conversacion",
            "limpia la conversacion",
        }:
            return False
        if (
            normalized in self._LIST_COMMANDS
            or normalized in self._CLEAR_COMMANDS
            or normalized in self._CLEAR_CONFIRMATIONS
            or normalized in {"cuantos recuerdos tienes", "estado de tu memoria"}
            or normalized in {"de que hablabamos", "en que nos quedamos", "que hablamos antes"}
            or MemoryExtractor.is_explicit_request(message)
            or self._FORGET_ONE.fullmatch(message) is not None
        ):
            return True
        with self._pending_lock:
            return session_id in self._pending_clear and normalized in self._CANCELLATIONS

    @staticmethod
    def _spoken_list(entries: tuple[MemoryEntry, ...], limit: int = 6) -> str:
        contents = [entry.content[:180].rstrip(".") for entry in entries[:limit]]
        return "; ".join(contents)

    def handle(self, session_id: str, message: str, profile_summary: str = "") -> str | None:
        if not self.settings.memory_enabled:
            return None
        normalized = normalize_memory_text(message).strip("¿¡!?. ")
        now = datetime.now(UTC)
        with self._pending_lock:
            expired = [key for key, deadline in self._pending_clear.items() if deadline < now]
            for key in expired:
                self._pending_clear.pop(key, None)
            pending = session_id in self._pending_clear

        if pending and normalized in self._CLEAR_CONFIRMATIONS:
            success = self.store.clear_all()
            with self._pending_lock:
                self._pending_clear.pop(session_id, None)
            return (
                "Eliminé los recuerdos aprendidos y las conversaciones recientes. "
                "Tu perfil personal base permanece intacto."
                if success
                else "No pude borrar la memoria local; el archivo no está disponible."
            )
        if pending and normalized in self._CANCELLATIONS:
            with self._pending_lock:
                self._pending_clear.pop(session_id, None)
            return "Cancelado. No eliminé ningún recuerdo."

        if normalized in self._CLEAR_COMMANDS:
            with self._pending_lock:
                self._pending_clear[session_id] = now + timedelta(seconds=60)
            return (
                "Eso eliminará los recuerdos aprendidos y las conversaciones recientes, pero no "
                "tu perfil base. Si estás seguro, di: confirmo borrar toda mi memoria."
            )

        if MemoryExtractor.is_explicit_request(message):
            if MemoryExtractor.contains_sensitive_data(message):
                return "No guardaré contraseñas, códigos, tokens ni datos bancarios en mi memoria."
            candidate = MemoryExtractor.explicit_candidate(message)
            if candidate is None:
                return "No pude identificar con precisión qué dato quieres que recuerde."
            entry = self.store.upsert(candidate)
            return (
                "Entendido. Guardé ese dato en mi memoria local."
                if entry is not None
                else "No pude guardar ese recuerdo en la memoria local."
            )

        if normalized in self._LIST_COMMANDS:
            entries = self.store.list_entries(8)
            learned = self._spoken_list(entries)
            if profile_summary and learned:
                return f"{profile_summary} Además, recuerdo que {learned}."
            if profile_summary:
                return profile_summary
            if learned:
                return f"Recuerdo que {learned}."
            return "Aún no tengo recuerdos aprendidos sobre ti."

        if normalized in {"cuantos recuerdos tienes", "estado de tu memoria"}:
            stats = self.store.stats()
            memory_label = "recuerdo aprendido" if stats.memories == 1 else "recuerdos aprendidos"
            session_label = "sesión reciente" if stats.sessions == 1 else "sesiones recientes"
            turn_label = "intercambio" if stats.turns == 1 else "intercambios"
            return (
                f"Tengo {stats.memories} {memory_label}. También conservo "
                f"{stats.sessions} {session_label}, con {stats.turns} {turn_label} en total, "
                "para dar continuidad; todo está guardado localmente."
            )

        if normalized in {"de que hablabamos", "en que nos quedamos", "que hablamos antes"}:
            recent = self.store.recent_turns(exclude_session=session_id, limit=2)
            if not recent:
                return "No tengo una conversación anterior reciente para retomar."
            user_text, assistant_text = recent[-1]
            return (
                f"Lo último que conversamos fue: tú dijiste {user_text[:300]}. "
                f"Yo respondí {assistant_text[:500]}."
            )

        forget = self._FORGET_ONE.fullmatch(message)
        if forget is not None:
            query = _clean_text(forget.group(1), 500)
            if normalize_memory_text(query) in {
                "todo",
                "todo lo que sabes de mi",
                "todos mis recuerdos",
            }:
                return self.handle(session_id, "borra toda tu memoria", profile_summary)
            removed = self.store.forget_best(query)
            return (
                f"Olvidé este dato: {removed.content}"
                if removed is not None
                else "No encontré un recuerdo suficientemente parecido para eliminarlo."
            )
        return None

    def learn(self, message: str) -> MemoryEntry | None:
        if not self.settings.memory_enabled:
            return None
        candidate = MemoryExtractor.implicit_candidate(message)
        return self.store.upsert(candidate) if candidate is not None else None

    def context(self, query: str) -> str:
        entries = self.store.relevant(query, self.settings.memory_context_items)
        lines: list[str] = []
        used = 0
        for entry in entries:
            line = f"- [{entry.category}] {entry.content}"
            if used + len(line) > 2_200:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def recent_context(self, session_id: str, query: str, limit: int = 3) -> str:
        query_tokens = self.store._tokens(query)
        if not query_tokens:
            return ""
        # Read a wider recent window before ranking. Filtering only the last three turns
        # allowed an unrelated conversation to contaminate a new model session.
        turns = self.store.recent_turns(
            exclude_session=session_id,
            limit=max(20, limit * 6),
        )
        ranked: list[tuple[int, int, str, str]] = []
        for position, (user_text, assistant_text) in enumerate(turns):
            if normalize_memory_text(user_text) == normalize_memory_text(query):
                continue
            # Rank only what Juan Diego actually said. Reusing an older model answer here
            # can promote one hallucination into apparent long-term personal context.
            turn_tokens = self.store._tokens(user_text)
            overlap = query_tokens & turn_tokens
            if overlap:
                ranked.append((len(overlap), position, user_text, assistant_text))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected_turns = sorted(ranked[: max(1, min(limit, 10))], key=lambda item: item[1])
        selected: list[str] = []
        used = 0
        for _, _, user_text, _ in selected_turns:
            block = f"Juan Diego comentó anteriormente: {user_text[:700]}"
            if used + len(block) > 2_400:
                break
            selected.append(block)
            used += len(block)
        return "\n\n".join(selected)

    def remember_exchange(self, session_id: str, user_text: str, assistant_text: str) -> bool:
        return self.store.add_turn(session_id, user_text, assistant_text)

    def reset_session(self, session_id: str) -> None:
        self.store.clear_session(session_id)
        with self._pending_lock:
            self._pending_clear.pop(session_id, None)
