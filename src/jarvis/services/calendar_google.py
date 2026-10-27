"""Separate Calendar OAuth grant and idempotent writes to a Jarvis-owned calendar."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

import httpx

from jarvis.services.mail import MailService
from jarvis.services.mail_providers import MailError
from jarvis.services.mail_store import MailStore

BASE = "https://www.googleapis.com/calendar/v3"
SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)


class GoogleCalendar(MailService):
    oauth_scope = SCOPES
    required_scope = "calendar.app.created"

    def __init__(self, config, mail, records):
        super().__init__(config, None)
        self.store = MailStore(config.data_dir / "calendar-auth.sqlite3")
        self.mail, self.records = mail, records
        self.write_lock = asyncio.Lock()

    async def start(self):
        self.client = httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False)

    async def begin_auth(self, provider="google"):
        config = self.mail.store.secret("client:google")
        if config:
            self.store.save_secret("client:google", config)
        return await super().begin_auth("google")

    async def finish_auth(self, pending, code):
        tokens = await self.token_request(
            "google",
            pending["config"],
            {
                "code": code,
                "code_verifier": pending["verifier"],
                "redirect_uri": pending["redirect"],
                "grant_type": "authorization_code",
            },
        )
        response = await self.client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": "Bearer " + tokens["access_token"]},
        )
        response.raise_for_status()
        email = response.json().get("email", "")
        if "@" not in email or not tokens.get("refresh_token"):
            raise MailError("Concede acceso a Calendar y vuelve a conectar")
        # A single destination prevents accidental publication to another account.
        for account in self.store.accounts():
            self.store.disconnect(account["id"])
        self.store.connect("google", email, {**tokens, "client": pending["config"]})
        self.records.replace("google_event", {})
        self.records.put("meta", "calendar_sync", {"synced": 0, "error": ""})

    def status(self):
        return {
            "accounts": self.store.accounts(),
            "configured": bool(self.mail.store.secret("client:google")),
            **self.records.get("meta", "calendar_sync", {"synced": 0, "error": ""}),
        }

    async def request(self, method, path, **kwargs):
        accounts = self.store.accounts()
        if not accounts:
            raise MailError("Conecta Google Calendar desde esta PC")
        token = await self.access_token(accounts[0])
        response = await self.client.request(
            method,
            BASE + path,
            headers={"Authorization": "Bearer " + token, **kwargs.pop("headers", {})},
            **kwargs,
        )
        if response.status_code not in (200, 201, 204, 409, 412):
            raise MailError("Calendar no pudo completar la operación; revisa permisos y conexión")
        return response

    async def managed_calendar(self):
        account = self.store.accounts()[0]
        key = "calendar:" + account["id"]
        existing = self.records.get("meta", key)
        if existing:
            return existing
        # Listing first recovers a successful create whose response was lost.
        calendars = await self.calendars()
        for item in calendars:
            if (
                item.get("description") == "Jarvis Local Core · calendario administrado"
                and item.get("accessRole") == "owner"
            ):
                return self.records.put("meta", key, item["id"])
        response = await self.request(
            "POST",
            "/calendars",
            json={
                "summary": "Jarvis",
                "timeZone": "America/Guayaquil",
                "description": "Jarvis Local Core · calendario administrado",
            },
        )
        return self.records.put("meta", key, response.json()["id"])

    async def calendars(self):
        items, page = [], None
        for _ in range(10):
            params = {"maxResults": 250, **({"pageToken": page} if page else {})}
            response = await self.request("GET", "/users/me/calendarList", params=params)
            data = response.json()
            items.extend(data.get("items", []))
            page = data.get("nextPageToken")
            if not page:
                return items
        raise MailError("Demasiados calendarios; no se actualizó la copia local")

    async def sync(self):
        if not self.store.accounts() or self.lock.locked():
            return
        async with self.lock:
            try:
                now = datetime.now(UTC)
                events = {}
                account = self.store.accounts()[0]
                managed_key = "calendar:" + account["id"]
                managed = self.records.get("meta", managed_key, "")
                calendars = await self.calendars()
                if not managed:
                    for calendar in calendars:
                        if (
                            calendar.get("description")
                            == "Jarvis Local Core · calendario administrado"
                            and calendar.get("accessRole") == "owner"
                        ):
                            managed = self.records.put("meta", managed_key, calendar["id"])
                            break
                for calendar in calendars:
                    if calendar.get("accessRole") not in {"owner", "writer", "reader"}:
                        continue
                    page = None
                    for _ in range(20):
                        params = {
                            "timeMin": (now - timedelta(days=45)).isoformat(),
                            "timeMax": (now + timedelta(days=365)).isoformat(),
                            "singleEvents": "true",
                            "maxResults": 250,
                            **({"pageToken": page} if page else {}),
                        }
                        response = await self.request(
                            "GET",
                            "/calendars/" + quote(calendar["id"], safe="") + "/events",
                            params=params,
                        )
                        data = response.json()
                        for event in data.get("items", []):
                            if event.get("status") == "cancelled":
                                continue
                            key = calendar["id"] + ":" + event["id"]
                            events[key] = {
                                "id": key,
                                "calendar_id": calendar["id"],
                                "event_id": event["id"],
                                "title": event.get("summary", "Ocupado"),
                                "description": event.get("description", "")[:4000],
                                "start_at": event.get("start", {}).get(
                                    "dateTime", event.get("start", {}).get("date", "")
                                ),
                                "end_at": event.get("end", {}).get(
                                    "dateTime", event.get("end", {}).get("date", "")
                                ),
                                "all_day": "date" in event.get("start", {}),
                                "busy": event.get("transparency") != "transparent",
                                "source": "Google Calendar",
                                "url": event.get("htmlLink", ""),
                                "calendar": calendar.get("summary", ""),
                                "etag": event.get("etag", ""),
                                "reminders": [
                                    int(item["minutes"])
                                    for item in event.get("reminders", {}).get("overrides", [])
                                    if item.get("method") == "popup"
                                    and isinstance(item.get("minutes"), int)
                                ][:5],
                                "editable": bool(
                                    managed
                                    and calendar["id"] == managed
                                    and calendar.get("accessRole") == "owner"
                                ),
                            }
                        page = data.get("nextPageToken")
                        if not page:
                            break
                    else:
                        raise MailError("Agenda demasiado grande; se conserva la copia anterior")
                if len(events) > 2000:
                    raise MailError("La agenda supera el límite de 2000 eventos sincronizados")
                self.records.replace("google_event", events)
                self.records.put("meta", "calendar_sync", {"synced": time.time(), "error": ""})
            except (MailError, httpx.HTTPError, ValueError, KeyError):
                previous = self.records.get("meta", "calendar_sync", {"synced": 0})
                self.records.put(
                    "meta",
                    "calendar_sync",
                    {
                        **previous,
                        "error": "No se pudo actualizar Calendar. Se reintentará; "
                        "la agenda mostrada puede estar desactualizada.",
                    },
                )

    @staticmethod
    def event_payload(event):
        field = "date" if event["all_day"] else "dateTime"
        payload = {
            "summary": event["title"],
            "description": event.get("description", ""),
            "start": {field: event["start_at"]},
            "end": {field: event["end_at"]},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": minutes}
                    for minutes in event.get("reminders", [])
                ],
            },
        }
        frequencies = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY"}
        if frequency := frequencies.get(event.get("recurrence", "")):
            payload["recurrence"] = [f"RRULE:FREQ={frequency}"]
        return payload

    @staticmethod
    def cached_event(calendar, event, fallback):
        key = calendar + ":" + event["id"]
        return key, {
            "id": key,
            "calendar_id": calendar,
            "event_id": event["id"],
            "title": event.get("summary", fallback["title"]),
            "description": event.get("description", fallback.get("description", ""))[:4000],
            "start_at": event.get("start", {}).get(
                "dateTime", event.get("start", {}).get("date", fallback["start_at"])
            ),
            "end_at": event.get("end", {}).get(
                "dateTime", event.get("end", {}).get("date", fallback["end_at"])
            ),
            "all_day": "date" in event.get("start", {}),
            "busy": event.get("transparency") != "transparent",
            "source": "Google Calendar",
            "url": event.get("htmlLink", fallback.get("url", "")),
            "calendar": "Jarvis",
            "etag": event.get("etag", ""),
            "reminders": list(fallback.get("reminders", [])),
            "editable": True,
            "recurrence": fallback.get("recurrence", ""),
        }

    async def create_managed_event(self, event):
        async with self.write_lock:
            managed = await self.managed_calendar()
            identifier = uuid4().hex
            path = "/calendars/" + quote(managed, safe="") + "/events"
            response = await self.request(
                "POST",
                path,
                json={"id": identifier, **self.event_payload(event)},
            )
            if response.status_code == 409:
                response = await self.request("GET", path + "/" + identifier)
            return self.cached_event(managed, response.json(), event)

    async def delete_managed_event(self, cached, etag):
        async with self.write_lock:
            managed = await self.managed_calendar()
            if not cached.get("editable") or cached.get("calendar_id") != managed:
                raise MailError("Solo se pueden eliminar eventos del calendario Jarvis")
            if not etag or cached.get("etag") != etag:
                raise MailError("El evento cambió; actualiza la agenda antes de eliminarlo")
            path = (
                "/calendars/"
                + quote(managed, safe="")
                + "/events/"
                + quote(cached["event_id"], safe="")
            )
            response = await self.request("DELETE", path, headers={"If-Match": etag})
            if response.status_code == 412:
                raise MailError(
                    "El evento fue modificado en Google. Actualiza la agenda antes de eliminarlo"
                )

    async def update_managed_event(self, cached, event):
        async with self.write_lock:
            managed = await self.managed_calendar()
            if (
                not cached.get("editable")
                or cached.get("calendar_id") != managed
                or cached.get("event_id") != event["event_id"]
            ):
                raise MailError("Solo se pueden editar eventos del calendario Jarvis")
            if cached.get("etag") != event["etag"]:
                raise MailError("El evento cambió; actualiza la agenda antes de guardarlo")
            path = (
                "/calendars/"
                + quote(managed, safe="")
                + "/events/"
                + quote(event["event_id"], safe="")
            )
            response = await self.request(
                "PATCH",
                path,
                json=self.event_payload(event),
                headers={"If-Match": event["etag"]},
            )
            if response.status_code == 412:
                raise MailError(
                    "El evento fue modificado en Google. Actualiza la agenda y revisa los cambios"
                )
            return self.cached_event(managed, response.json(), {**cached, **event})

    async def publish(self, proposal):
        async with self.write_lock:
            calendar = await self.managed_calendar()
            identifier = hashlib.sha256(proposal["source_key"].encode()).hexdigest()
            path = "/calendars/" + quote(calendar, safe="") + "/events"
            link_key = calendar + ":" + identifier
            old = self.records.get("calendar_link", link_key)
            field = "date" if proposal["all_day"] else "dateTime"
            payload = self.event_payload(proposal)
            digest = hashlib.sha256(str(payload).encode()).hexdigest()
            if old and old["digest"] == digest:
                return old
            if old:
                response = await self.request(
                    "PATCH",
                    path + "/" + identifier,
                    json=payload,
                    headers={"If-Match": old["etag"]},
                )
                if response.status_code == 412:
                    # Distinguish a lost successful PATCH from an external edit.
                    current = (await self.request("GET", path + "/" + identifier)).json()
                    if any(
                        current.get(k) != v for k, v in payload.items() if k not in {"start", "end"}
                    ) or any(
                        not same_time(current.get(k, {}).get(field), payload[k][field])
                        for k in ("start", "end")
                    ):
                        raise MailError(
                            "El evento cambió en Google. "
                            "Revísalo allí antes de modificarlo desde Jarvis"
                        )
                    response_data = current
                else:
                    response_data = response.json()
            else:
                response = await self.request("POST", path, json={"id": identifier, **payload})
                if response.status_code == 409:
                    response = await self.request("GET", path + "/" + identifier)
                    current = response.json()
                    if any(
                        current.get(k) != v for k, v in payload.items() if k not in {"start", "end"}
                    ) or any(
                        not same_time(current.get(k, {}).get(field), payload[k][field])
                        for k in ("start", "end")
                    ):
                        raise MailError(
                            "Ya existe este evento con otros datos. Revisa Google Calendar"
                        )
                response_data = response.json()
            return self.records.put(
                "calendar_link",
                link_key,
                {
                    "id": identifier,
                    "calendar_id": calendar,
                    "url": response_data.get("htmlLink", ""),
                    "etag": response_data["etag"],
                    "digest": digest,
                },
            )


def same_time(left, right):
    if not left or not right:
        return False
    if len(left) == 10 or len(right) == 10:
        return left == right
    try:
        return datetime.fromisoformat(left.replace("Z", "+00:00")) == datetime.fromisoformat(
            right.replace("Z", "+00:00")
        )
    except ValueError:
        return False
