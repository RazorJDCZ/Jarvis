from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, Protocol
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx


class ConnectorError(RuntimeError):
    pass


_PRIORITIES = frozenset({"baja", "media", "alta"})
_CATEGORIES = frozenset(
    {"universidad", "personal", "trabajo", "finanzas", "salud", "otros"}
)


def _has_control(value: str, *, allow_layout: bool = False) -> bool:
    allowed = {"\n", "\t"} if allow_layout else set()
    return any(
        unicodedata.category(character) == "Cc" and character not in allowed
        for character in value
    )


@dataclass(frozen=True, slots=True)
class AppaBridgeDescriptor:
    schema_version: int
    enabled: bool
    host: str
    port: int
    base_url: str
    token: str
    api_version: str
    generated_at: str


@dataclass(frozen=True, slots=True)
class TaskItem:
    task_id: str
    title: str
    notes: str
    due: str | None
    completed: bool
    source: str
    created_at: str
    priority: str = "media"
    category: str = "personal"
    reminder_at: str | None = None
    project_id: str | None = None
    updated_at: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.task_id,
            "title": self.title,
            "notes": self.notes,
            "due": self.due,
            "completed": self.completed,
            "source": self.source,
            "created_at": self.created_at,
            "priority": self.priority,
            "category": self.category,
            "reminder_at": self.reminder_at,
            "project_id": self.project_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ProjectItem:
    project_id: str
    name: str
    description: str
    status: str
    target_date: str | None
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "target_date": self.target_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class CalendarItem:
    event_id: str
    title: str
    description: str
    start_at: str
    end_at: str | None
    source_type: str
    source_id: str | None
    completed: bool
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.event_id,
            "title": self.title,
            "description": self.description,
            "start_at": self.start_at,
            "end_at": self.end_at,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "completed": self.completed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class InboxItem:
    item_id: str
    text: str
    source: str
    archived: bool
    created_at: str
    updated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "text": self.text,
            "source": self.source,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class FocusItem:
    session_id: str
    task_id: str | None
    task_title: str | None
    duration_minutes: int
    remaining_seconds: int
    status: str
    started_at: str
    planned_end_at: str | None
    completed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.session_id,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "duration_minutes": self.duration_minutes,
            "remaining_seconds": self.remaining_seconds,
            "status": self.status,
            "started_at": self.started_at,
            "planned_end_at": self.planned_end_at,
            "completed": self.completed,
        }


class TaskConnector(Protocol):
    name: str

    async def status(self) -> dict[str, object]: ...

    async def list_tasks(
        self, session_id: str, include_completed: bool = False
    ) -> list[TaskItem]: ...

    async def create_task(
        self,
        session_id: str,
        title: str,
        notes: str = "",
        due: str | None = None,
        *,
        priority: str = "media",
        category: str = "personal",
        reminder_at: str | None = None,
        project_id: str | None = None,
    ) -> TaskItem: ...

    async def complete_task(self, session_id: str, task_id: str) -> TaskItem: ...


def _is_link_or_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return path.is_symlink() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    except OSError:
        return False


def load_appa_bridge_descriptor(path: Path) -> AppaBridgeDescriptor:
    """Load Appa's local descriptor without accepting an attacker-controlled endpoint."""

    path = Path(path).absolute()
    if path.name.casefold() != "jarvis-bridge.json":
        raise ConnectorError("El descriptor local de Appa no tiene el nombre esperado.")
    if _is_link_or_reparse(path) or _is_link_or_reparse(path.parent):
        raise ConnectorError("El descriptor local de Appa no puede ser un enlace.")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16_384:
            raise ConnectorError("El descriptor local de Appa no es un archivo seguro.")
        if os.name != "nt":
            getuid = getattr(os, "getuid", None)
            if callable(getuid) and metadata.st_uid != getuid():
                raise ConnectorError("El descriptor local de Appa pertenece a otro usuario.")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ConnectorError(
                    "El descriptor local de Appa tiene permisos demasiado amplios."
                )
        raw = resolved.read_bytes()
    except ConnectorError:
        raise
    except (OSError, ValueError) as exc:
        raise ConnectorError("No pude leer el descriptor local de Appa.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConnectorError("El descriptor local de Appa no contiene JSON v\u00e1lido.") from exc
    if not isinstance(payload, dict):
        raise ConnectorError("El descriptor local de Appa no es v\u00e1lido.")

    schema_version = payload.get("schema_version")
    enabled = payload.get("enabled")
    host = payload.get("host")
    port = payload.get("port")
    base_url = payload.get("base_url")
    token = payload.get("token")
    api_version = payload.get("api_version")
    generated_at = payload.get("generated_at")
    if schema_version != 1 or isinstance(schema_version, bool):
        raise ConnectorError("La versi\u00f3n del descriptor de Appa no es compatible.")
    if not isinstance(enabled, bool):
        raise ConnectorError("El estado del puente de Appa no es v\u00e1lido.")
    if host != "127.0.0.1":
        raise ConnectorError("El puente de Appa debe escuchar exclusivamente en 127.0.0.1.")
    if not isinstance(port, int) or isinstance(port, bool) or not 1_024 <= port <= 65_535:
        raise ConnectorError("El puerto del puente de Appa no es v\u00e1lido.")
    expected_url = f"http://127.0.0.1:{port}/v1"
    if base_url != expected_url or api_version != "v1":
        raise ConnectorError("El endpoint del puente de Appa no coincide con su contrato local.")
    if (
        not isinstance(token, str)
        or not 32 <= len(token) <= 256
        or re.fullmatch(r"[A-Za-z0-9._~-]+", token) is None
    ):
        raise ConnectorError("El token local de Appa no es v\u00e1lido.")
    if not isinstance(generated_at, str) or len(generated_at) > 80:
        raise ConnectorError("La fecha del descriptor de Appa no es v\u00e1lida.")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorError("La fecha del descriptor de Appa no es v\u00e1lida.") from exc
    if generated.tzinfo is None:
        raise ConnectorError("La fecha del descriptor de Appa debe incluir zona horaria.")
    return AppaBridgeDescriptor(
        schema_version=schema_version,
        enabled=enabled,
        host=host,
        port=port,
        base_url=base_url,
        token=token,
        api_version=api_version,
        generated_at=generated_at,
    )


class LocalTaskConnector:
    """A zero-cost local task backend used until Appa exposes its API."""

    name = "local-tasks"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    due TEXT,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    priority TEXT NOT NULL DEFAULT 'media',
                    category TEXT NOT NULL DEFAULT 'personal',
                    reminder_at TEXT,
                    project_id TEXT,
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            additions = {
                "priority": "TEXT NOT NULL DEFAULT 'media'",
                "category": "TEXT NOT NULL DEFAULT 'personal'",
                "reminder_at": "TEXT",
                "project_id": "TEXT",
                "updated_at": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in additions.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id, completed)"
            )

    @staticmethod
    def _clean(value: str, maximum: int, field: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > maximum or _has_control(cleaned):
            raise ConnectorError(f"El campo {field} no es v\u00e1lido.")
        return cleaned

    @staticmethod
    def _optional_text(value: str | None, maximum: int, field: str) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > maximum or _has_control(cleaned):
            raise ConnectorError(f"El campo {field} no es v\u00e1lido.")
        return cleaned

    @staticmethod
    def _item(row: sqlite3.Row) -> TaskItem:
        return TaskItem(
            task_id=str(row["task_id"]),
            title=str(row["title"]),
            notes=str(row["notes"]),
            due=str(row["due"]) if row["due"] else None,
            completed=bool(row["completed"]),
            source="local",
            created_at=str(row["created_at"]),
            priority=str(row["priority"]),
            category=str(row["category"]),
            reminder_at=str(row["reminder_at"]) if row["reminder_at"] else None,
            project_id=str(row["project_id"]) if row["project_id"] else None,
            updated_at=str(row["updated_at"] or row["created_at"]),
        )

    async def status(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": True,
            "mode": "local",
            "detail": "Tareas privadas guardadas en SQLite dentro de Jarvis.",
        }

    def has_tasks(self) -> bool:
        """Report whether switching stores could strand existing local task data."""

        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT 1 FROM tasks LIMIT 1").fetchone()
        return row is not None

    async def list_tasks(self, session_id: str, include_completed: bool = False) -> list[TaskItem]:
        query = "SELECT * FROM tasks WHERE session_id = ?"
        arguments: list[object] = [session_id]
        if not include_completed:
            query += " AND completed = 0"
        query += " ORDER BY COALESCE(due, '9999'), created_at LIMIT 200"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, arguments).fetchall()
        return [self._item(row) for row in rows]

    async def create_task(
        self,
        session_id: str,
        title: str,
        notes: str = "",
        due: str | None = None,
        *,
        priority: str = "media",
        category: str = "personal",
        reminder_at: str | None = None,
        project_id: str | None = None,
    ) -> TaskItem:
        title = self._clean(title, 300, "t\u00edtulo")
        notes = notes.strip()
        if len(notes) > 4_000 or _has_control(notes, allow_layout=True):
            raise ConnectorError("El campo notas no es v\u00e1lido.")
        due = AppaConnector._task_date_only(due, "fecha")
        priority = priority.strip().casefold()
        category = category.strip().casefold()
        if priority not in _PRIORITIES or category not in _CATEGORIES:
            raise ConnectorError("La prioridad o categor\u00eda de la tarea no es v\u00e1lida.")
        reminder_at = AppaConnector._rfc3339(
            reminder_at, "recordatorio", required=False
        )
        project_id = self._optional_text(project_id, 128, "proyecto")
        task_id = uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO tasks(
                    task_id, session_id, title, notes, due, created_at,
                    priority, category, reminder_at, project_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    session_id,
                    title,
                    notes,
                    due,
                    created_at,
                    priority,
                    category,
                    reminder_at,
                    project_id,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ? AND session_id = ?",
                (task_id, session_id),
            ).fetchone()
        if row is None:
            raise ConnectorError("No pude verificar la tarea creada.")
        return self._item(row)

    async def complete_task(self, session_id: str, task_id: str) -> TaskItem:
        completed_at = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE tasks SET completed = 1, completed_at = ?, updated_at = ?
                WHERE task_id = ? AND session_id = ? AND completed = 0""",
                (completed_at, completed_at, task_id, session_id),
            )
            if cursor.rowcount != 1:
                raise ConnectorError(
                    "La tarea no existe, ya termin\u00f3 o pertenece a otra sesi\u00f3n."
                )
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ? AND session_id = ?",
                (task_id, session_id),
            ).fetchone()
        if row is None:
            raise ConnectorError("No pude verificar la tarea completada.")
        return self._item(row)


class AppaConnector:
    """Small, opt-in REST adapter; no Appa data leaves the configured endpoint."""

    name = "appa"
    _TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    _MAX_RESPONSE_BYTES = 1024 * 1024
    _PROJECT_STATUSES = frozenset({"active", "paused", "completed", "archived"})
    _FOCUS_STATUSES = frozenset({"active", "paused", "stopped", "completed"})

    def __init__(self, base_url: str, token: str, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = max(2.0, min(timeout, 30.0))
        parsed = urlsplit(self.base_url)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ConnectorError("La URL de Appa contiene un puerto inv\u00e1lido.") from exc
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        path_parts = tuple(part for part in parsed.path.split("/") if part)
        if not parsed.hostname or (parsed.scheme != "https" and not local_http):
            raise ConnectorError("Appa requiere HTTPS o una API local en loopback.")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(part in {".", ".."} for part in path_parts)
        ):
            raise ConnectorError("La URL base de Appa contiene componentes no permitidos.")
        if len(self.token) > 4_096 or _has_control(self.token):
            raise ConnectorError("El token de Appa no es v\u00e1lido.")
        self._client: httpx.AsyncClient | None = None
        self._capabilities: frozenset[str] = frozenset()
        self._capabilities_expires_at = 0.0

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        return self._client

    @staticmethod
    def _decode(item: object) -> TaskItem:
        if not isinstance(item, dict):
            raise ConnectorError("Appa devolvi\u00f3 una tarea inv\u00e1lida.")
        task_id = item.get("id")
        title = item.get("title")
        notes = item.get("notes", item.get("description", ""))
        due = item.get("due", item.get("due_date", item.get("dueDate")))
        reminder_at = item.get("reminder_at", item.get("reminderAt"))
        project_id = item.get("project_id", item.get("projectId"))
        created_at = item.get("created_at", item.get("createdAt", ""))
        updated_at = item.get("updated_at", item.get("updatedAt", ""))
        priority = item.get("priority", "media")
        category = item.get("category", "personal")
        completed = item.get("completed", False)
        strings = (task_id, title, notes, created_at, updated_at, priority, category)
        optional_strings = (due, reminder_at, project_id)
        if (
            not all(isinstance(value, str) for value in strings)
            or not all(value is None or isinstance(value, str) for value in optional_strings)
            or not isinstance(completed, bool)
        ):
            raise ConnectorError("Appa devolvi\u00f3 una tarea incompleta.")
        task_id = task_id.strip()
        title = title.strip()
        notes = notes.strip()
        priority = priority.strip().casefold()
        category = category.strip().casefold()
        if (
            AppaConnector._TASK_ID.fullmatch(task_id) is None
            or not 1 <= len(title) <= 300
            or len(notes) > 4_000
            or priority not in _PRIORITIES
            or category not in _CATEGORIES
            or _has_control(title)
            or _has_control(notes, allow_layout=True)
        ):
            raise ConnectorError("Appa devolvi\u00f3 una tarea incompleta.")
        for value in optional_strings:
            if value is not None and (
                len(value) > 128 or _has_control(value)
            ):
                raise ConnectorError("Appa devolvi\u00f3 una tarea incompleta.")
        for value in (created_at, updated_at):
            if len(value) > 80 or _has_control(value):
                raise ConnectorError("Appa devolvi\u00f3 una tarea incompleta.")
        normalized_due = AppaConnector._date_or_rfc3339(due, "fecha")
        normalized_reminder = AppaConnector._rfc3339(
            reminder_at, "recordatorio", required=False
        )
        return TaskItem(
            task_id=task_id,
            title=title,
            notes=notes,
            due=normalized_due,
            completed=completed,
            source="appa",
            created_at=created_at.strip()[:80],
            priority=priority,
            category=category,
            reminder_at=normalized_reminder,
            project_id=project_id.strip() if project_id else None,
            updated_at=updated_at.strip()[:80],
        )

    @classmethod
    def _required_text(
        cls,
        payload: dict[str, object],
        key: str,
        maximum: int,
        *,
        allow_newlines: bool = False,
    ) -> str:
        value = payload.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum
            or _has_control(value, allow_layout=allow_newlines)
        ):
            raise ConnectorError("Appa devolvi\u00f3 datos incompletos.")
        return value.strip()

    @classmethod
    def _optional_response_text(
        cls,
        payload: dict[str, object],
        key: str,
        maximum: int,
    ) -> str | None:
        value = payload.get(key)
        if value is None or value == "":
            return None
        if (
            not isinstance(value, str)
            or len(value.strip()) > maximum
            or _has_control(value)
        ):
            raise ConnectorError("Appa devolvi\u00f3 datos incompletos.")
        return value.strip() or None

    @classmethod
    def _identifier(cls, payload: dict[str, object]) -> str:
        item_id = cls._required_text(payload, "id", 128)
        if cls._TASK_ID.fullmatch(item_id) is None:
            raise ConnectorError("Appa devolvi\u00f3 un identificador inv\u00e1lido.")
        return item_id

    @classmethod
    def _decode_project(cls, item: object) -> ProjectItem:
        if not isinstance(item, dict):
            raise ConnectorError("Appa devolvi\u00f3 un proyecto inv\u00e1lido.")
        status = cls._required_text(item, "status", 24).casefold()
        if status not in cls._PROJECT_STATUSES:
            raise ConnectorError("Appa devolvi\u00f3 un estado de proyecto inv\u00e1lido.")
        description = item.get("description", "")
        if description is None:
            description = ""
        if (
            not isinstance(description, str)
            or len(description) > 4_000
            or _has_control(description, allow_layout=True)
        ):
            raise ConnectorError("Appa devolvi\u00f3 un proyecto inv\u00e1lido.")
        target_date = cls._optional_response_text(item, "target_date", 80)
        return ProjectItem(
            project_id=cls._identifier(item),
            name=cls._required_text(item, "name", 300),
            description=description.strip(),
            status=status,
            target_date=cls._date_or_rfc3339(target_date, "fecha objetivo"),
            created_at=cls._required_text(item, "created_at", 80),
            updated_at=cls._required_text(item, "updated_at", 80),
        )

    @classmethod
    def _decode_calendar(cls, item: object) -> CalendarItem:
        if not isinstance(item, dict):
            raise ConnectorError("Appa devolvi\u00f3 un evento inv\u00e1lido.")
        completed = item.get("completed", False)
        if not isinstance(completed, bool):
            raise ConnectorError("Appa devolvi\u00f3 un evento inv\u00e1lido.")
        description = item.get("description", "")
        if description is None:
            description = ""
        if (
            not isinstance(description, str)
            or len(description) > 4_000
            or _has_control(description, allow_layout=True)
        ):
            raise ConnectorError("Appa devolvi\u00f3 un evento inv\u00e1lido.")
        start_at = cls._rfc3339(
            cls._required_text(item, "start_at", 80), "inicio", required=True
        )
        end_at = cls._rfc3339(
            cls._optional_response_text(item, "end_at", 80), "fin", required=False
        )
        if start_at is None:
            raise ConnectorError("Appa devolvi\u00f3 un evento inv\u00e1lido.")
        return CalendarItem(
            event_id=cls._identifier(item),
            title=cls._required_text(item, "title", 300),
            description=description.strip(),
            start_at=start_at,
            end_at=end_at,
            source_type=cls._required_text(item, "source_type", 40),
            source_id=cls._optional_response_text(item, "source_id", 128),
            completed=completed,
            created_at=cls._required_text(item, "created_at", 80),
            updated_at=cls._required_text(item, "updated_at", 80),
        )

    @classmethod
    def _decode_inbox(cls, item: object) -> InboxItem:
        if not isinstance(item, dict):
            raise ConnectorError("Appa devolvi\u00f3 una captura inv\u00e1lida.")
        archived = item.get("archived", False)
        if not isinstance(archived, bool):
            raise ConnectorError("Appa devolvi\u00f3 una captura inv\u00e1lida.")
        return InboxItem(
            item_id=cls._identifier(item),
            text=cls._required_text(item, "text", 4_000, allow_newlines=True),
            source=cls._required_text(item, "source", 80),
            archived=archived,
            created_at=cls._required_text(item, "created_at", 80),
            updated_at=cls._required_text(item, "updated_at", 80),
        )

    @classmethod
    def _decode_focus(cls, item: object) -> FocusItem:
        if not isinstance(item, dict):
            raise ConnectorError("Appa devolvi\u00f3 una sesi\u00f3n focus inv\u00e1lida.")
        status = cls._required_text(item, "status", 24).casefold()
        duration = item.get("duration_minutes")
        remaining = item.get("remaining_seconds")
        completed = item.get("completed", False)
        if (
            status not in cls._FOCUS_STATUSES
            or not isinstance(duration, int)
            or isinstance(duration, bool)
            or not 1 <= duration <= 180
            or not isinstance(remaining, int)
            or isinstance(remaining, bool)
            or not 0 <= remaining <= 180 * 60
            or not isinstance(completed, bool)
        ):
            raise ConnectorError("Appa devolvi\u00f3 una sesi\u00f3n focus inv\u00e1lida.")
        started_at = cls._rfc3339(
            cls._required_text(item, "started_at", 80), "inicio focus", required=True
        )
        planned_end_at = cls._rfc3339(
            cls._optional_response_text(item, "planned_end_at", 80),
            "fin focus",
            required=False,
        )
        if started_at is None:
            raise ConnectorError("Appa devolvi\u00f3 una sesi\u00f3n focus inv\u00e1lida.")
        return FocusItem(
            session_id=cls._identifier(item),
            task_id=cls._optional_response_text(item, "task_id", 128),
            task_title=cls._optional_response_text(item, "task_title", 300),
            duration_minutes=duration,
            remaining_seconds=remaining,
            status=status,
            started_at=started_at,
            planned_end_at=planned_end_at,
            completed=completed,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json_body: dict[str, object] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http_client().request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json_body,
                headers={**self._headers, **(extra_headers or {})},
            )
        except httpx.RequestError:
            raise ConnectorError(
                "Appa no responde. Abre Appa o d\u00e9jala activa en la bandeja del sistema."
            ) from None
        if len(response.content) > self._MAX_RESPONSE_BYTES:
            raise ConnectorError("Appa devolvi\u00f3 una respuesta demasiado grande.")
        if response.is_success:
            return response
        detail = {
            400: "Appa rechaz\u00f3 los datos enviados.",
            401: "El token local de Appa ya no es v\u00e1lido; se recargar\u00e1 su descriptor.",
            404: "El recurso ya no existe en Appa.",
            409: "Appa est\u00e1 ocupada; vuelve a intentarlo en un momento.",
            413: "La solicitud supera el l\u00edmite aceptado por Appa.",
        }.get(response.status_code, "Appa no pudo completar la operaci\u00f3n.")
        raise ConnectorError(detail)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except (UnicodeError, ValueError):
            raise ConnectorError("Appa devolvi\u00f3 JSON inv\u00e1lido.") from None

    async def _load_capabilities(self, *, force: bool = False) -> frozenset[str]:
        if not force and time.monotonic() < self._capabilities_expires_at:
            return self._capabilities
        response = await self._request("GET", "/health")
        payload = self._json(response)
        capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "ok"
            or payload.get("service") != "appa-jarvis-bridge"
            or payload.get("api_version") != "v1"
            or not isinstance(capabilities, list)
            or len(capabilities) > 64
            or any(
                not isinstance(value, str)
                or re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None
                for value in capabilities
            )
        ):
            raise ConnectorError("El puente local de Appa no es compatible.")
        self._capabilities = frozenset(capabilities)
        self._capabilities_expires_at = time.monotonic() + 30.0
        return self._capabilities

    async def _require_capabilities(self, *required: str) -> None:
        capabilities = await self._load_capabilities()
        missing = set(required).difference(capabilities)
        if missing:
            raise ConnectorError(
                "La versi\u00f3n activa de Appa no ofrece esta capacidad a Jarvis. "
                "Actualiza y reinicia Appa."
            )

    async def status(self) -> dict[str, object]:
        try:
            capabilities = await self._load_capabilities(force=True)
            if not {"tasks.read", "tasks.write"}.issubset(capabilities):
                raise ConnectorError("El puente local de Appa no es compatible.")
            return {
                "name": self.name,
                "available": True,
                "mode": "appa-bridge-v1",
                "detail": "Conectado al puente privado de Appa.",
            }
        except ConnectorError as exc:
            return {
                "name": self.name,
                "available": False,
                "mode": "appa-bridge-v1",
                "detail": str(exc),
            }

    async def list_tasks(self, session_id: str, include_completed: bool = False) -> list[TaskItem]:
        del session_id
        await self._require_capabilities("tasks.read")
        response = await self._request(
            "GET",
            "/tasks",
            params={
                "include_completed": str(include_completed).lower(),
                "limit": 200,
            },
        )
        payload = self._json(response)
        items = payload.get("tasks", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ConnectorError("Appa devolvi\u00f3 un listado inv\u00e1lido.")
        return [self._decode(item) for item in items[:200]]

    async def create_task(
        self,
        session_id: str,
        title: str,
        notes: str = "",
        due: str | None = None,
        *,
        priority: str = "media",
        category: str = "personal",
        reminder_at: str | None = None,
        project_id: str | None = None,
    ) -> TaskItem:
        del session_id
        title = LocalTaskConnector._clean(title, 300, "t\u00edtulo")
        notes = notes.strip()
        if len(notes) > 4_000 or _has_control(notes, allow_layout=True):
            raise ConnectorError("El campo notas no es v\u00e1lido.")
        due = self._task_date_only(due, "fecha")
        reminder_at = self._rfc3339(reminder_at, "recordatorio", required=False)
        project_id = LocalTaskConnector._optional_text(project_id, 128, "proyecto")
        priority = priority.strip().casefold()
        category = category.strip().casefold()
        if priority not in _PRIORITIES or category not in _CATEGORIES:
            raise ConnectorError("La prioridad o categor\u00eda de la tarea no es v\u00e1lida.")
        await self._require_capabilities("tasks.write")
        payload = {
            "title": title,
            "notes": notes,
            "due": due,
            "reminder_at": reminder_at,
            "project_id": project_id,
            "priority": priority,
            "category": category,
        }
        response = await self._request(
            "POST",
            "/tasks",
            json_body=payload,
            extra_headers={"Idempotency-Key": uuid4().hex},
        )
        return self._decode(self._json(response))

    async def complete_task(self, session_id: str, task_id: str) -> TaskItem:
        del session_id
        task_id = task_id.strip()
        if self._TASK_ID.fullmatch(task_id) is None:
            raise ConnectorError("El identificador de tarea de Appa no es v\u00e1lido.")
        await self._require_capabilities("tasks.write")
        encoded_task_id = quote(task_id, safe="")
        response = await self._request(
            "PATCH",
            f"/tasks/{encoded_task_id}",
            json_body={"completed": True},
        )
        task = self._decode(self._json(response))
        if task.task_id != task_id or not task.completed:
            raise ConnectorError("Appa no confirm\u00f3 la tarea completada.")
        return task

    @staticmethod
    def _collection(payload: object, key: str) -> list[object]:
        items = payload.get(key, payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ConnectorError("Appa devolvi\u00f3 un listado inv\u00e1lido.")
        return items[:200]

    @staticmethod
    def _task_date_only(value: str | None, field: str) -> str | None:
        cleaned = LocalTaskConnector._optional_text(value, 10, field)
        if cleaned is None:
            return None
        try:
            parsed = datetime.strptime(cleaned, "%Y-%m-%d")
        except ValueError as exc:
            raise ConnectorError(f"El campo {field} no usa una fecha v\u00e1lida.") from exc
        if parsed.strftime("%Y-%m-%d") != cleaned:
            raise ConnectorError(f"El campo {field} no usa una fecha v\u00e1lida.")
        return cleaned

    @staticmethod
    def _date_or_rfc3339(value: str | None, field: str) -> str | None:
        cleaned = LocalTaskConnector._optional_text(value, 80, field)
        if cleaned is None:
            return None
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
                parsed = datetime.strptime(cleaned, "%Y-%m-%d")
                if parsed.strftime("%Y-%m-%d") != cleaned:
                    raise ValueError
                return cleaned
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectorError(f"El campo {field} no usa una fecha v\u00e1lida.") from exc
        if parsed.tzinfo is None:
            raise ConnectorError(f"El campo {field} debe incluir zona horaria.")
        return parsed.isoformat()

    @staticmethod
    def _rfc3339(value: str | None, field: str, *, required: bool) -> str | None:
        cleaned = LocalTaskConnector._optional_text(value, 80, field)
        if cleaned is None:
            if required:
                raise ConnectorError(f"El campo {field} es obligatorio.")
            return None
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectorError(f"El campo {field} no usa una fecha v\u00e1lida.") from exc
        if parsed.tzinfo is None:
            raise ConnectorError(f"El campo {field} debe incluir zona horaria.")
        return parsed.isoformat()

    async def list_projects(self) -> list[ProjectItem]:
        await self._require_capabilities("projects.read")
        response = await self._request("GET", "/projects", params={"limit": 200})
        items = self._collection(self._json(response), "projects")
        return [self._decode_project(item) for item in items]

    async def create_project(
        self,
        name: str,
        description: str = "",
        target_date: str | None = None,
    ) -> ProjectItem:
        name = LocalTaskConnector._clean(name, 300, "nombre")
        description = description.strip()
        if len(description) > 4_000 or _has_control(description, allow_layout=True):
            raise ConnectorError("La descripci\u00f3n del proyecto no es v\u00e1lida.")
        target_date = self._date_or_rfc3339(target_date, "fecha objetivo")
        await self._require_capabilities("projects.write")
        response = await self._request(
            "POST",
            "/projects",
            json_body={
                "name": name,
                "description": description,
                "status": "active",
                "target_date": target_date,
            },
            extra_headers={"Idempotency-Key": uuid4().hex},
        )
        return self._decode_project(self._json(response))

    async def list_calendar(self) -> list[CalendarItem]:
        await self._require_capabilities("calendar.read")
        response = await self._request("GET", "/calendar/events", params={"limit": 200})
        items = self._collection(self._json(response), "events")
        return [self._decode_calendar(item) for item in items]

    async def create_calendar_event(
        self,
        title: str,
        start_at: str,
        description: str = "",
        end_at: str | None = None,
    ) -> CalendarItem:
        title = LocalTaskConnector._clean(title, 300, "t\u00edtulo")
        description = description.strip()
        if len(description) > 4_000 or _has_control(description, allow_layout=True):
            raise ConnectorError("La descripci\u00f3n del evento no es v\u00e1lida.")
        normalized_start = self._rfc3339(start_at, "inicio", required=True)
        normalized_end = self._rfc3339(end_at, "fin", required=False)
        if normalized_start is None:
            raise ConnectorError("El inicio del evento es obligatorio.")
        if normalized_end is not None and datetime.fromisoformat(
            normalized_end
        ) <= datetime.fromisoformat(normalized_start):
            raise ConnectorError("El fin del evento debe ser posterior al inicio.")
        await self._require_capabilities("calendar.write")
        response = await self._request(
            "POST",
            "/calendar/events",
            json_body={
                "title": title,
                "description": description,
                "start_at": normalized_start,
                "end_at": normalized_end,
            },
            extra_headers={"Idempotency-Key": uuid4().hex},
        )
        return self._decode_calendar(self._json(response))

    async def list_inbox(self, include_archived: bool = False) -> list[InboxItem]:
        await self._require_capabilities("inbox.read")
        response = await self._request(
            "GET",
            "/inbox",
            params={
                "include_archived": str(include_archived).lower(),
                "limit": 200,
            },
        )
        items = self._collection(self._json(response), "items")
        return [self._decode_inbox(item) for item in items]

    async def capture_inbox(self, value: str) -> InboxItem:
        text = value.strip()
        if (
            not text
            or len(text) > 4_000
            or _has_control(text, allow_layout=True)
        ):
            raise ConnectorError("La captura para Appa no es v\u00e1lida.")
        await self._require_capabilities("inbox.write")
        response = await self._request(
            "POST",
            "/inbox",
            json_body={"text": text},
            extra_headers={"Idempotency-Key": uuid4().hex},
        )
        return self._decode_inbox(self._json(response))

    async def focus_status(self) -> FocusItem | None:
        await self._require_capabilities("focus.read")
        response = await self._request("GET", "/focus", params={"limit": 100})
        sessions = [
            self._decode_focus(item)
            for item in self._collection(self._json(response), "sessions")[:100]
        ]
        active = next(
            (item for item in sessions if item.status in {"active", "paused"}),
            None,
        )
        if active is None or active.status != "active" or active.planned_end_at is None:
            return active
        planned_end = datetime.fromisoformat(active.planned_end_at)
        remaining = max(0, int((planned_end - datetime.now(UTC)).total_seconds()))
        return FocusItem(
            session_id=active.session_id,
            task_id=active.task_id,
            task_title=active.task_title,
            duration_minutes=active.duration_minutes,
            remaining_seconds=remaining,
            status=active.status,
            started_at=active.started_at,
            planned_end_at=active.planned_end_at,
            completed=active.completed,
        )

    async def start_focus(
        self,
        duration_minutes: int,
        task_id: str | None = None,
        task_title: str | None = None,
    ) -> FocusItem:
        if (
            not isinstance(duration_minutes, int)
            or isinstance(duration_minutes, bool)
            or not 5 <= duration_minutes <= 180
        ):
            raise ConnectorError("La sesi\u00f3n focus debe durar entre 5 y 180 minutos.")
        task_id = LocalTaskConnector._optional_text(task_id, 128, "tarea")
        task_title = LocalTaskConnector._optional_text(task_title, 300, "t\u00edtulo")
        await self._require_capabilities("focus.write")
        response = await self._request(
            "POST",
            "/focus",
            json_body={
                "duration_minutes": duration_minutes,
                "task_id": task_id,
                "task_title": task_title,
            },
            extra_headers={"Idempotency-Key": uuid4().hex},
        )
        return self._decode_focus(self._json(response))


class UnavailableTaskConnector:
    name = "appa"

    def __init__(self, detail: str) -> None:
        self.detail = detail

    async def status(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": False,
            "mode": "appa-bridge-v1",
            "detail": self.detail,
        }

    def _raise(self) -> NoReturn:
        raise ConnectorError(self.detail)

    async def list_tasks(
        self, session_id: str, include_completed: bool = False
    ) -> list[TaskItem]:
        del session_id, include_completed
        self._raise()

    async def create_task(
        self,
        session_id: str,
        title: str,
        notes: str = "",
        due: str | None = None,
        *,
        priority: str = "media",
        category: str = "personal",
        reminder_at: str | None = None,
        project_id: str | None = None,
    ) -> TaskItem:
        del (
            session_id,
            title,
            notes,
            due,
            priority,
            category,
            reminder_at,
            project_id,
        )
        self._raise()

    async def complete_task(self, session_id: str, task_id: str) -> TaskItem:
        del session_id, task_id
        self._raise()


class ConnectorRegistry:
    _UNSET = object()

    def __init__(
        self,
        local: LocalTaskConnector,
        appa: AppaConnector | None = None,
        *,
        bridge_config_path: Path | None = None,
        bridge_database_marker: Path | None = None,
        bridge_required: bool = False,
        appa_timeout: float = 8.0,
    ) -> None:
        self.local = local
        self.appa = appa
        self.bridge_config_path = bridge_config_path
        self.bridge_database_marker = bridge_database_marker
        self.bridge_required = bridge_required
        self.appa_timeout = appa_timeout
        self._explicit_appa = appa is not None
        self._bridge_fingerprint: object = self._UNSET
        self._bridge_connector: TaskConnector | None = None
        self._bridge_activated = self._explicit_appa
        self._retired_connectors: list[AppaConnector] = []
        self._lock = threading.RLock()

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int, int, int] | None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ConnectorError("No pude consultar el descriptor local de Appa.") from exc
        return (
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_size,
            metadata.st_ino,
        )

    def _replace_bridge_connector(self, connector: TaskConnector | None) -> None:
        current = self._bridge_connector
        if isinstance(current, AppaConnector) and current is not connector:
            self._retired_connectors.append(current)
        self._bridge_connector = connector
        self.appa = connector if isinstance(connector, AppaConnector) else None
        if isinstance(connector, AppaConnector):
            self._bridge_activated = True

    def _discover_bridge(self) -> TaskConnector | None:
        if self._explicit_appa:
            return self.appa
        path = self.bridge_config_path
        if path is None:
            return None
        with self._lock:
            fingerprint_error: str | None = None
            try:
                fingerprint = self._fingerprint(path)
            except ConnectorError as exc:
                fingerprint = None
                fingerprint_error = str(exc)
            comparison: object = (
                ("error", fingerprint_error) if fingerprint_error is not None else fingerprint
            )
            if comparison == self._bridge_fingerprint:
                return self._bridge_connector
            self._bridge_fingerprint = comparison
            if fingerprint_error is not None:
                self._replace_bridge_connector(
                    UnavailableTaskConnector(fingerprint_error)
                )
                return self._bridge_connector
            if fingerprint is None:
                marker_exists = bool(
                    self.bridge_database_marker is not None
                    and self.bridge_database_marker.is_file()
                )
                if self.bridge_required or marker_exists or self._bridge_activated:
                    self._replace_bridge_connector(
                        UnavailableTaskConnector(
                            "Detect\u00e9 Appa, pero su puente privado no est\u00e1 disponible. "
                            "Abre Appa y d\u00e9jala activa en la bandeja del sistema."
                        )
                    )
                else:
                    self._replace_bridge_connector(None)
                return self._bridge_connector
            try:
                descriptor = load_appa_bridge_descriptor(path)
                if not descriptor.enabled:
                    raise ConnectorError(
                        "El puente privado de Appa est\u00e1 desactivado en Appa."
                    )
                if self.local.has_tasks():
                    raise ConnectorError(
                        "Hay tareas previas en el almac\u00e9n local de Jarvis. "
                        "No cambiar\u00e9 a Appa autom\u00e1ticamente para evitar "
                        "dividir tus datos."
                    )
                connector: TaskConnector = AppaConnector(
                    descriptor.base_url,
                    descriptor.token,
                    self.appa_timeout,
                )
            except ConnectorError as exc:
                connector = UnavailableTaskConnector(str(exc))
            self._replace_bridge_connector(connector)
            return self._bridge_connector

    @property
    def tasks(self) -> TaskConnector:
        return self._discover_bridge() or self.local

    def require_appa(self) -> AppaConnector:
        selected = self._discover_bridge()
        if isinstance(selected, AppaConnector):
            return selected
        if isinstance(selected, UnavailableTaskConnector):
            raise ConnectorError(selected.detail)
        raise ConnectorError(
            "Appa no est\u00e1 disponible. Inicia Appa y d\u00e9jala activa en la bandeja."
        )

    async def statuses(self) -> list[dict[str, object]]:
        selected = self.tasks
        local_status = await self.local.status()
        local_status["active"] = selected is self.local
        statuses = [local_status]
        if selected is not self.local:
            appa_status = await selected.status()
            appa_status["active"] = True
            statuses.append(appa_status)
        else:
            statuses.append(
                {
                    "name": "appa",
                    "available": False,
                    "mode": "not-configured",
                    "active": False,
                    "detail": (
                        "Appa no est\u00e1 detectada; Jarvis usa su almac\u00e9n local privado."
                    ),
                }
            )
        return statuses

    async def close(self) -> None:
        connectors: list[AppaConnector] = list(self._retired_connectors)
        for candidate in (self.appa, self._bridge_connector):
            if isinstance(candidate, AppaConnector) and candidate not in connectors:
                connectors.append(candidate)
        for connector in connectors:
            await connector.close()
        self._retired_connectors.clear()
