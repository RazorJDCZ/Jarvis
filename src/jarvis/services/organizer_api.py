from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.services.mail_providers import MailError
from jarvis.services.organizer import (
    CalendarEventEdit,
    EventReview,
    StudyRequest,
    inbox_session,
)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{16,64}$")
    due_at: str | None = Field(default=None, max_length=40)


class FollowupSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    after_days: int = Field(default=3, ge=1, le=30)
    repeat_hours: int = Field(default=24, ge=24, le=720)


class SubscriptionRequest(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str]
    expirationTime: float | None = None


def organizer_router(service, require_local, effective_session, web_dir):
    router = APIRouter()

    def session(request):
        # One persistent organizer inbox per authenticated device, independent of chat tabs.
        return inbox_session(effective_session(request, "organizer"))

    @router.get("/organizer")
    async def page():
        return FileResponse(web_dir / "organizer.html", headers={"Cache-Control": "no-store"})

    @router.get("/api/organizer/today")
    async def today(request: Request):
        return service.today(session(request))

    @router.post("/api/organizer/refresh")
    async def refresh(request: Request):
        await service.refresh(force=True)
        return {"refreshed": True}

    @router.post("/api/organizer/calendar/connect")
    async def connect(request: Request):
        require_local(request)
        try:
            return {"url": await service.calendar.begin_auth()}
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.delete("/api/organizer/calendar")
    async def disconnect(request: Request):
        require_local(request)
        async with service.lock, service.calendar.write_lock, service.calendar.lock:
            for account in service.calendar.store.accounts():
                service.calendar.store.disconnect(account["id"])
            service.store.replace("google_event", {})
            service.store.put("meta", "calendar_sync", {"synced": 0, "error": ""})
        return {"disconnected": True}

    @router.patch("/api/organizer/calendar/events")
    async def edit_event(request: Request, payload: CalendarEventEdit):
        require_local(request)
        try:
            return await service.edit_google_event(payload)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "No se pudo actualizar el evento en Google Calendar") from None

    @router.post("/api/organizer/proposals/{identifier}/publish")
    async def publish(request: Request, identifier: str, payload: EventReview):
        require_local(request)
        try:
            return await service.publish(identifier, payload)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(
                503, "No se pudo guardar en Google. Puedes reintentar sin duplicar el evento"
            ) from None

    @router.delete("/api/organizer/proposals/{identifier}")
    async def dismiss(request: Request, identifier: str):
        require_local(request)
        proposal = service.store.get("proposal", identifier)
        if not proposal:
            raise HTTPException(404, "Propuesta no disponible")
        service.store.put("proposal", identifier, {**proposal, "state": "dismissed"})
        return {"dismissed": True}

    @router.post("/api/organizer/study")
    async def study(request: Request, payload: StudyRequest):
        require_local(request)
        try:
            await service.refresh(force=True)
            return service.study(payload)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/api/organizer/captures")
    async def capture(request: Request, payload: CaptureRequest):
        try:
            return service.capture(
                payload.text, session(request), payload.request_id, payload.due_at
            )
        except (MailError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None

    @router.delete("/api/organizer/captures/{identifier}")
    async def complete(request: Request, identifier: str):
        item = service.store.get("capture", identifier)
        if not item or (session(request) != "local:inbox" and item["session"] != session(request)):
            raise HTTPException(404, "Captura no disponible")
        service.store.put("capture", identifier, {**item, "done": True})
        return {"completed": True}

    @router.put("/api/organizer/followups")
    async def followups(request: Request, payload: FollowupSettings):
        require_local(request)
        return service.store.put("meta", "followups", payload.model_dump())

    @router.get("/api/organizer/push")
    async def push_status(request: Request):
        subscriptions = [
            s for s in service.store.list("subscription") if s["session"] == session(request)
        ]
        return {
            "public_key": service.push.keys()["public"],
            "subscriptions": [{"id": s["id"], "error": s["error"]} for s in subscriptions],
        }

    @router.post("/api/organizer/push")
    async def subscribe(request: Request, payload: SubscriptionRequest):
        device = getattr(request.state, "remote_device", None)
        try:
            return service.push.subscribe(
                payload.model_dump(), session(request), device.device_id if device else ""
            )
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.delete("/api/organizer/push/{identifier}")
    async def unsubscribe(request: Request, identifier: str):
        item = service.store.get("subscription", identifier)
        if not item or item["session"] != session(request):
            raise HTTPException(404, "Suscripción no disponible")
        service.store.delete("subscription", identifier)
        return {"removed": True}

    @router.post("/api/organizer/push/test")
    async def test_push(request: Request):
        if not service.capabilities:
            raise HTTPException(503, "Activa las capacidades de Jarvis")
        key = "push-test:" + session(request)
        if service.store.seen(key, 30):
            raise HTTPException(429, "Espera 30 segundos antes de repetir la prueba")
        await service.capabilities._notify(
            session(request),
            {"event": "test", "id": str(time.time_ns()), "title": "Prueba de avisos"},
        )
        service.store.put("throttle", key, time.time())
        return {"queued": True}

    @router.post("/api/organizer/backups")
    async def backup(request: Request):
        require_local(request)
        return await asyncio.to_thread(service.recovery.backup)

    return router
