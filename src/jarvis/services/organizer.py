"""Cached daily view, reviewed mail events, deterministic study slots and quick capture."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.services.calendar_google import GoogleCalendar
from jarvis.services.finance import FinanceTracker
from jarvis.services.mail_providers import MailError
from jarvis.services.organizer_store import OrganizerStore

TZ = ZoneInfo("America/Guayaquil")
APPA_DESKTOP_SESSION = "appa:desktop"
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def moment(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed


def inbox_session(session):
    return (
        ":".join(session.split(":")[:2]) + ":inbox"
        if session.startswith("remote:")
        else "local:inbox"
    )


class EventReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    start_at: str = Field(max_length=40)
    end_at: str = Field(max_length=40)
    all_day: bool = False
    reminders: list[int] = Field(default_factory=lambda: [1440, 60], max_length=5)
    revision: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_times(self):
        if any(m < 0 or m > 40320 for m in self.reminders):
            raise ValueError("Recordatorios entre 0 y 40320 minutos")
        if self.all_day:
            date.fromisoformat(self.start_at)
            date.fromisoformat(self.end_at)
        elif any(
            datetime.fromisoformat(t.replace("Z", "+00:00")).tzinfo is None
            for t in (self.start_at, self.end_at)
        ):
            raise ValueError("Indica la zona horaria")
        if moment(self.end_at) <= moment(self.start_at):
            raise ValueError("El fin debe ser posterior al inicio")
        if moment(self.end_at) - moment(self.start_at) > timedelta(days=31):
            raise ValueError("El evento no puede superar 31 días")
        return self


class CalendarEventEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=1024)
    etag: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    start_at: str = Field(max_length=40)
    end_at: str = Field(max_length=40)
    all_day: bool = False
    reminders: list[int] = Field(default_factory=lambda: [1440, 60], max_length=5)

    @model_validator(mode="after")
    def valid_times(self):
        if any(minutes < 0 or minutes > 40320 for minutes in self.reminders):
            raise ValueError("Recordatorios entre 0 y 40320 minutos")
        if self.all_day:
            date.fromisoformat(self.start_at)
            date.fromisoformat(self.end_at)
        elif any(
            datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None
            for value in (self.start_at, self.end_at)
        ):
            raise ValueError("Indica la zona horaria")
        if moment(self.end_at) <= moment(self.start_at):
            raise ValueError("El fin debe ser posterior al inicio")
        if moment(self.end_at) - moment(self.start_at) > timedelta(days=31):
            raise ValueError("El evento no puede superar 31 días")
        return self


class CalendarEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    start_at: str = Field(max_length=40)
    end_at: str = Field(max_length=40)
    all_day: bool = False
    reminders: list[int] = Field(default_factory=lambda: [1440, 60], max_length=5)
    recurrence: Literal["", "daily", "weekly", "monthly"] = ""

    @model_validator(mode="after")
    def valid_times(self):
        if any(minutes < 0 or minutes > 40320 for minutes in self.reminders):
            raise ValueError("Recordatorios entre 0 y 40320 minutos")
        if self.all_day:
            date.fromisoformat(self.start_at)
            date.fromisoformat(self.end_at)
        elif any(
            datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None
            for value in (self.start_at, self.end_at)
        ):
            raise ValueError("Indica la zona horaria")
        if moment(self.end_at) <= moment(self.start_at):
            raise ValueError("El fin debe ser posterior al inicio")
        if moment(self.end_at) - moment(self.start_at) > timedelta(days=31):
            raise ValueError("El evento no puede superar 31 días")
        return self


class StudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deadline: date
    sessions: int = Field(default=3, ge=1, le=20)
    minutes: int = Field(default=45, ge=15, le=180)
    start_hour: int = Field(default=16, ge=0, le=22)
    end_hour: int = Field(default=20, ge=1, le=23)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)


def date_suggestion(text, received):
    """Only explicit dates are filled. Relative/ambiguous wording stays for review."""
    match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    warning = "Confirma fecha y hora antes de agendar."
    day = None
    try:
        if match:
            day = date(*map(int, match.groups()))
        else:
            match = re.search(
                r"\b(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")(?:\s+(?:de\s+)?(20\d{2}))?\b",
                text.lower(),
            )
            if match and match[3]:
                day = date(int(match[3]), MONTHS.index(match[2]) + 1, int(match[1]))
            elif match:
                warning = "El correo no indica el año. Completa la fecha."
    except ValueError:
        warning = "La fecha mencionada no es válida; corrígela."
    hour = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if day and hour:
        start = datetime.combine(day, datetime.min.time(), TZ).replace(
            hour=int(hour[1]), minute=int(hour[2])
        )
        return (
            start.isoformat(),
            (start + timedelta(hours=1)).isoformat(),
            False,
            warning + " Duración sugerida: 1 hora; revisa la zona horaria.",
        )
    if day:
        return (
            day.isoformat(),
            (day + timedelta(days=1)).isoformat(),
            True,
            "Sin hora explícita: se propone todo el día.",
        )
    return (
        "",
        "",
        True,
        warning + " Las fechas relativas se muestran sin interpretarlas automáticamente.",
    )


class Organizer:
    def __init__(self, config, mail, capabilities):
        self.config, self.mail, self.capabilities = config, mail, capabilities
        self.store = OrganizerStore(config.data_dir / "organizer.sqlite3")
        self.calendar = GoogleCalendar(config, mail, self.store)
        self.finance = FinanceTracker(mail.store, self.store)
        self.worker = None
        self.lock = asyncio.Lock()
        self.push = None
        self.recovery = None

    async def start(self):
        if self.capabilities:
            try:
                self.capabilities.connectors.require_appa()
            except Exception:
                pass
            else:
                await asyncio.to_thread(self.capabilities.outbox.register, APPA_DESKTOP_SESSION)
        await self.calendar.start()
        self.worker = asyncio.create_task(self._loop())

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        await self.calendar.close()

    async def _loop(self):
        while True:
            try:
                await self.refresh()
                self.store.delete("meta", "worker_error")
                self.proposals()
                await self.followups()
                if self.recovery:
                    await asyncio.to_thread(self.recovery.daily)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.store.put(
                    "meta", "worker_error", "No se pudo completar la revisión; se reintentará"
                )
            resource_mode = self.reliability_settings()["resource_mode"]
            await asyncio.sleep(180 if resource_mode == "eco" else 60)

    async def refresh(self, force=False):
        if self.lock.locked():
            return
        async with self.lock:
            status = self.calendar.status()
            if force or time.time() - status["synced"] > 300:
                await self.calendar.sync()
            if self.capabilities:
                try:
                    connector = self.capabilities.connectors.require_appa()
                    tasks, events = await asyncio.wait_for(
                        asyncio.gather(
                            connector.list_tasks("organizer"), connector.list_calendar()
                        ),
                        8,
                    )
                    self.store.put(
                        "meta",
                        "appa",
                        {
                            "tasks": [t.as_dict() for t in tasks],
                            "events": [e.as_dict() for e in events],
                            "synced": time.time(),
                            "error": "",
                        },
                    )
                except Exception:
                    cached = self.store.get(
                        "meta", "appa", {"tasks": [], "events": [], "synced": 0}
                    )
                    self.store.put(
                        "meta",
                        "appa",
                        {**cached, "error": "Appa no está disponible; se muestra la última copia"},
                    )

    def proposals(self):
        for item in self.mail.store.list():
            if not item["deadline"]:
                continue
            key = "mail:" + item["id"]
            old = self.store.get("proposal", key)
            if old and old["mail_version"] == item["version"]:
                continue
            start, end, all_day, warning = date_suggestion(item["deadline"], item["received"])
            self.store.put(
                "proposal",
                key,
                {
                    "id": key,
                    "source_key": key,
                    "revision": uuid4().hex,
                    "mail_id": item["id"],
                    "mail_version": item["version"],
                    "title": item["subject"],
                    "description": item["summary"] + "\n" + item["url"],
                    "quote": item["deadline"],
                    "url": item["url"],
                    "start_at": start,
                    "end_at": end,
                    "all_day": all_day,
                    "reminders": [1440, 60],
                    "state": "review",
                    "warning": (
                        "El correo cambió. Revisa si corresponde actualizar el evento. "
                        if old
                        else ""
                    )
                    + warning,
                    "published": old.get("published") if old else None,
                },
            )
        # Disconnected, resolved and snoozed mail stops suggesting actions.
        result = []
        for proposal in self.store.list("proposal"):
            if proposal.get("mail_id"):
                item = self.mail.store.get(proposal["mail_id"])
                if (
                    not item
                    or item["version"] != proposal["mail_version"]
                    or item["state"] == "resolved"
                    or item["snoozed_until"] > time.time()
                ):
                    continue
            if proposal["state"] == "review":
                result.append(proposal)
        return result

    async def publish(self, identifier, review):
        async with self.lock:
            proposal = self.store.get("proposal", identifier)
            if not proposal or proposal["revision"] != review.revision:
                raise MailError("La propuesta cambió; actualiza la vista")
            if proposal.get("mail_id"):
                item = self.mail.store.get(proposal["mail_id"])
                if (
                    not item
                    or item["version"] != proposal["mail_version"]
                    or item["state"] == "resolved"
                ):
                    raise MailError("El correo cambió o fue resuelto; revisa la propuesta")
            updated = {**proposal, **review.model_dump()}
            if proposal.get("pending_publish") and any(
                proposal.get(k) != v for k, v in review.model_dump().items()
            ):
                raise MailError(
                    "Hay un guardado pendiente. Recarga y reintenta sus datos antes de cambiarlos"
                )
            self.store.put("proposal", identifier, {**updated, "pending_publish": True})
            published = await self.calendar.publish(updated)
            self.store.put(
                "proposal",
                identifier,
                {**updated, "state": "published", "published": published, "pending_publish": False},
            )
            key = published["calendar_id"] + ":" + published["id"]
            self.store.put(
                "google_event",
                key,
                {
                    "id": key,
                    "calendar_id": published["calendar_id"],
                    "event_id": published["id"],
                    "title": updated["title"],
                    "description": updated.get("description", ""),
                    "start_at": updated["start_at"],
                    "end_at": updated["end_at"],
                    "all_day": updated["all_day"],
                    "busy": True,
                    "source": "Google Calendar",
                    "url": published.get("url", ""),
                    "calendar": "Jarvis",
                    "etag": published["etag"],
                    "reminders": updated.get("reminders", []),
                    "editable": True,
                },
            )
            self.store.put("meta", "calendar_sync", {"synced": 0, "error": ""})
            return published

    def resolve_google_event(self, selector: str):
        selector = selector.strip()
        events = [event for event in self.store.list("google_event") if event.get("editable")]
        direct = next(
            (event for event in events if selector in {event.get("id"), event.get("event_id")}),
            None,
        )
        if direct:
            return direct
        normalized = selector.casefold()
        matches = [event for event in events if normalized in event.get("title", "").casefold()]
        if not matches:
            raise MailError("No encontré ese evento en el calendario Jarvis")
        exact = [event for event in matches if event.get("title", "").casefold() == normalized]
        candidates = exact or matches
        if len(candidates) != 1:
            options = "; ".join(
                f"{event['title']} — {event['start_at']}" for event in candidates[:5]
            )
            raise MailError("Encontré varios eventos. Indica cuál: " + options)
        return candidates[0]

    async def edit_google_event(self, edit: CalendarEventEdit):
        async with self.lock:
            cached = self.store.get("google_event", edit.event_id)
            if not cached:
                cached = self.resolve_google_event(edit.event_id)
            payload = {**edit.model_dump(), "event_id": cached["event_id"]}
            key, updated = await self.calendar.update_managed_event(cached, payload)
            self.store.put("google_event", key, updated)
            self.store.put("meta", "calendar_sync", {"synced": 0, "error": ""})
            return updated

    async def create_google_event(self, event: CalendarEventCreate):
        async with self.lock:
            key, created = await self.calendar.create_managed_event(event.model_dump())
            self.store.put("google_event", key, created)
            self.store.put("meta", "calendar_sync", {"synced": 0, "error": ""})
            return created

    async def delete_google_event(self, event_id: str, etag: str):
        async with self.lock:
            cached = self.store.get("google_event", event_id)
            if not cached:
                cached = self.resolve_google_event(event_id)
            await self.calendar.delete_managed_event(cached, etag)
            self.store.delete("google_event", cached["id"])
            self.store.put("meta", "calendar_sync", {"synced": 0, "error": ""})
            return {"deleted": True, "id": cached["id"]}

    def events(self):
        appa = self.store.get("meta", "appa", {})
        return self.store.list("google_event") + [
            {**e, "source": "Appa", "busy": True}
            for e in appa.get("events", [])
            if not e.get("completed")
        ]

    def calendar_events(self, start_at: str = "", end_at: str = ""):
        """Return the cached calendar in a bounded date range, including past days."""

        now = datetime.now(TZ)
        try:
            start = moment(start_at) if start_at else now - timedelta(days=45)
            end = moment(end_at) if end_at else now + timedelta(days=365)
        except ValueError as exc:
            raise ValueError("Rango de calendario no válido") from exc
        if end <= start or end - start > timedelta(days=730):
            raise ValueError("El rango debe cubrir entre 1 y 730 días")
        result = []
        for event in self.events():
            try:
                event_start = moment(event["start_at"])
                event_end = moment(event.get("end_at") or event["start_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if event_start < end and event_end >= start:
                result.append(event)
        result.sort(key=lambda item: moment(item["start_at"]))
        return {
            "events": result[:2_000],
            "calendar": self.calendar.status(),
            "range": {"start_at": start.isoformat(), "end_at": end.isoformat()},
        }

    def today(self, session="default"):
        session = inbox_session(session)
        now = datetime.now(TZ)
        appa = self.store.get("meta", "appa", {"tasks": [], "events": [], "synced": 0})
        tasks = [{**t, "due_date": t.get("due")} for t in appa["tasks"] if not t.get("completed")]
        tasks.sort(key=lambda t: (t.get("due_date") or "9999", t.get("priority") != "alta"))
        mail = self.mail.store.list()
        events = []
        for e in self.events():
            try:
                if moment(e["end_at"] or e["start_at"]) >= now:
                    events.append(e)
            except (ValueError, KeyError):
                continue
        events.sort(key=lambda e: moment(e["start_at"]))
        priorities = [
            {
                "title": t["title"],
                "reason": "Tarea con fecha próxima" if t.get("due_date") else "Tarea pendiente",
                "source": "Appa",
            }
            for t in tasks[:2]
        ]
        priorities += [
            {
                "title": m["subject"],
                "reason": "Correo por responder"
                if m["state"] == "reply"
                else "Correo con prioridad sugerida alta",
                "source": "Correo",
            }
            for m in mail
            if m["state"] == "reply" or m["priority"] == "high"
        ]
        priorities += [
            {"title": e["title"], "reason": "Próximo compromiso", "source": e["source"]}
            for e in events
        ]
        return {
            "date": now.date().isoformat(),
            "timezone": str(TZ),
            "priorities": priorities[:3],
            "tasks": tasks[:30],
            "events": events[:100],
            "mail": mail[:20],
            "proposals": self.proposals(),
            "calendar": self.calendar.status(),
            "appa": {k: appa.get(k) for k in ("synced", "error")},
            "captures": [
                c
                for c in self.store.list("capture")
                if (session == "local:inbox" or c["session"] == session) and not c.get("done")
            ][:50],
            "followup_settings": self.followup_settings(),
            "finance": self.finance.summary(),
            "recovery": self.recovery.status() if self.recovery else {},
        }

    def reliability_settings(self):
        stored = self.store.get("meta", "reliability_settings", {})
        return {
            "resource_mode": (
                stored.get("resource_mode")
                if stored.get("resource_mode") in {"normal", "eco"}
                else "normal"
            )
        }

    def set_resource_mode(self, mode: str):
        if mode not in {"normal", "eco"}:
            raise ValueError("El modo de recursos no es válido")
        value = {"resource_mode": mode, "updated": time.time()}
        self.store.put("meta", "reliability_settings", value)
        return {"updated": True, **value}

    def reliability(self):
        now = time.time()
        recovery = (
            self.recovery.diagnostics()
            if self.recovery
            else {
                "status": "warning",
                "checks": [],
                "backups": [],
            }
        )
        services: list[dict[str, object]] = []

        mail = self.mail.status()
        accounts = mail["accounts"]
        if not accounts:
            mail_state, mail_detail = "warning", "No hay cuentas de correo conectadas"
        elif any(account.get("error") for account in accounts):
            mail_state = "error"
            mail_detail = " · ".join(
                str(account.get("error")) for account in accounts if account.get("error")
            )[:300]
        elif any(account.get("progress") for account in accounts) or mail["syncing"]:
            mail_state, mail_detail = "warning", "Sincronización incremental en curso"
        else:
            oldest = min(float(account.get("synced") or 0) for account in accounts)
            age_minutes = int((now - oldest) / 60) if oldest else 0
            mail_state = "warning" if not oldest or age_minutes > 20 else "ok"
            mail_detail = (
                f"{len(accounts)} cuenta(s) · última revisión hace {age_minutes} min"
                if oldest
                else "Conectado; primera sincronización pendiente"
            )
        services.append(
            {"id": "mail", "name": "Gmail y correo", "status": mail_state, "detail": mail_detail}
        )

        calendar_status = self.calendar.status()
        calendar_accounts = calendar_status.get("accounts", [])
        calendar_error = str(calendar_status.get("error") or "")
        calendar_synced = float(calendar_status.get("synced") or 0)
        if calendar_error:
            calendar_state, calendar_detail = "error", calendar_error
        elif not calendar_accounts:
            calendar_state, calendar_detail = "warning", "Google Calendar no está conectado"
        else:
            calendar_age = int((now - calendar_synced) / 60) if calendar_synced else 0
            calendar_state = "warning" if not calendar_synced or calendar_age > 20 else "ok"
            calendar_detail = (
                f"Sincronizado hace {calendar_age} min"
                if calendar_synced
                else "Primera sincronización pendiente"
            )
        services.append(
            {
                "id": "calendar",
                "name": "Google Calendar",
                "status": calendar_state,
                "detail": calendar_detail,
            }
        )

        appa = self.store.get("meta", "appa", {"synced": 0, "error": ""})
        appa_error = str(appa.get("error") or "")
        appa_synced = float(appa.get("synced") or 0)
        appa_age = int((now - appa_synced) / 60) if appa_synced else 0
        services.append(
            {
                "id": "appa",
                "name": "Appa",
                "status": (
                    "error"
                    if appa_error
                    else "warning"
                    if not appa_synced or appa_age > 10
                    else "ok"
                ),
                "detail": appa_error
                or (
                    f"Puente verificado hace {appa_age} min"
                    if appa_synced
                    else "Appa aún no respondió"
                ),
            }
        )
        services.append(
            {
                "id": "scheduler",
                "name": "Revisión proactiva",
                "status": "error" if self.store.get("meta", "worker_error") else "ok",
                "detail": self.store.get("meta", "worker_error")
                or "Programador activo y sin errores pendientes",
            }
        )
        states = [recovery["status"], *(item["status"] for item in services)]
        overall = "error" if "error" in states else "warning" if "warning" in states else "ok"
        return {
            "status": overall,
            "checked_at": now,
            "settings": self.reliability_settings(),
            "services": services,
            "recovery": recovery,
        }

    def capture(self, text, session, request_id, due_at=None):
        session = inbox_session(session)
        key = session + ":" + request_id
        old = self.store.get("capture", key)
        if old:
            return old
        if not text.strip():
            raise MailError("Escribe una idea o pendiente")
        if due_at and (
            datetime.fromisoformat(due_at.replace("Z", "+00:00")).tzinfo is None
            or moment(due_at) <= datetime.now(UTC)
        ):
            raise MailError("El recordatorio debe ser futuro")
        return self.store.put(
            "capture",
            key,
            {
                "id": key,
                "session": session,
                "text": text.strip(),
                "created": time.time(),
                "due_at": due_at,
                "done": False,
            },
        )

    def followup_settings(self):
        return self.store.get(
            "meta", "followups", {"enabled": True, "after_days": 3, "repeat_hours": 24}
        )

    async def followups(self):
        if not self.capabilities:
            return
        preferences = self.capabilities.preferences
        now = datetime.now(TZ)
        if preferences.quiet(now.hour):
            return
        settings = self.followup_settings()
        sessions = set(self.capabilities.outbox.sessions())
        if self.push:
            sessions.update(s["session"] for s in self.store.list("subscription"))
        for session in sessions:
            for event in self.events():
                try:
                    delta = (moment(event["start_at"]) - now).total_seconds()
                except (KeyError, ValueError):
                    continue
                if 0 < delta <= 900:
                    await self.capabilities._notify(
                        session,
                        {
                            "event": "agenda-upcoming",
                            "id": event["id"] + ":" + event["start_at"],
                            "title": "Próximo: " + event["title"],
                            "due_at": event["start_at"],
                        },
                    )
        for capture in self.store.list("capture"):
            if (
                capture.get("due_at")
                and not capture.get("done")
                and moment(capture["due_at"]) <= now
            ):
                await self.capabilities._notify(
                    capture["session"],
                    {
                        "event": "capture-reminder",
                        "id": capture["id"],
                        "title": capture["text"],
                        "due_at": capture["due_at"],
                    },
                )
        if not settings["enabled"]:
            return
        for item in self.mail.store.list():
            if item["state"] not in {"reply", "waiting"}:
                continue
            since = self.store.get("mail_state", item["id"])
            if not since or since["state"] != item["state"] or since["version"] != item["version"]:
                since = self.store.put(
                    "mail_state",
                    item["id"],
                    {"state": item["state"], "version": item["version"], "since": time.time()},
                )
            if time.time() - since["since"] < settings["after_days"] * 86400:
                continue
            key = "mail:" + item["id"] + ":" + item["version"]
            if self.store.seen(key, settings["repeat_hours"] * 3600):
                continue
            for session in sessions:
                await self.capabilities._notify(
                    session,
                    {
                        "event": "mail-followup",
                        "id": key + ":" + now.date().isoformat(),
                        "title": (
                            "Pendiente de respuesta: "
                            if item["state"] == "reply"
                            else "Sigue esperando respuesta: "
                        )
                        + item["subject"],
                    },
                )
            if sessions:
                self.store.put("throttle", key, time.time())

    def study(self, request):
        today = datetime.now(TZ)
        if not today.date() < request.deadline <= today.date() + timedelta(days=90):
            raise MailError("Elige una fecha entre mañana y los próximos 90 días")
        if request.start_hour >= request.end_hour or any(
            d not in range(7) for d in request.weekdays
        ):
            raise MailError("Horario de estudio inválido")
        busy = []
        for event in self.events() + self.store.list("proposal"):
            if event.get("busy", True) and event.get("state") != "dismissed":
                try:
                    busy.append(
                        (
                            moment(event["start_at"]),
                            moment(event["end_at"] or event["start_at"]) + timedelta(minutes=10),
                        )
                    )
                except (ValueError, KeyError):
                    continue
        plan_id, slots = uuid4().hex, []
        day = today.date()
        while day < request.deadline and len(slots) < request.sessions:
            if day.weekday() in request.weekdays:
                start = datetime.combine(day, datetime.min.time(), TZ).replace(
                    hour=request.start_hour
                )
                limit = start.replace(hour=request.end_hour)
                while start + timedelta(minutes=request.minutes) <= limit:
                    end = start + timedelta(minutes=request.minutes)
                    if start > today and all(end <= a or start >= b for a, b in busy):
                        key = "study:" + plan_id + ":" + str(len(slots))
                        proposal = {
                            "id": key,
                            "source_key": key,
                            "revision": uuid4().hex,
                            "title": "Estudiar: " + request.title,
                            "start_at": start.isoformat(),
                            "end_at": end.isoformat(),
                            "all_day": False,
                            "reminders": [15],
                            "description": "Preparación para " + request.deadline.isoformat(),
                            "state": "review",
                            "quote": "",
                            "warning": "Horario propuesto según la agenda disponible. "
                            "Revisa antes de guardar.",
                        }
                        self.store.put("proposal", key, proposal)
                        slots.append(proposal)
                        break  # Spread sessions across days.
                    start += timedelta(minutes=15)
            day += timedelta(days=1)
        status = self.calendar.status()
        return {
            "slots": slots,
            "missing": request.sessions - len(slots),
            "warning": "Se usó la agenda almacenada. "
            + (
                "Google Calendar aún no está conectado."
                if not status["accounts"]
                else "Última sincronización: " + str(status["synced"])
            ),
        }
