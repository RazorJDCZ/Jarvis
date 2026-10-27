from __future__ import annotations

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from jarvis.services.mail_providers import MailError
from jarvis.services.organizer import (
    CalendarEventCreate,
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


class CalendarEventDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=1024)
    etag: str = Field(min_length=1, max_length=500)


class FinanceTransactionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=500)
    category: Literal[
        "alimentacion",
        "transporte",
        "compras",
        "entretenimiento",
        "salud",
        "servicios",
        "educacion",
        "donaciones",
        "transferencias",
        "efectivo",
        "otros",
    ]
    included: bool = True
    merchant: str | None = Field(default=None, min_length=1, max_length=100)
    remember_merchant: bool = False


class FinanceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(default="", pattern=r"^(?:|\d{4}-(?:0[1-9]|1[0-2]))$")


class FinanceBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal[
        "total",
        "alimentacion",
        "transporte",
        "compras",
        "entretenimiento",
        "salud",
        "servicios",
        "educacion",
        "donaciones",
        "transferencias",
        "efectivo",
        "otros",
    ]
    monthly_limit: str = Field(pattern=r"^\d{1,8}(?:[.,]\d{1,2})?$")


class FinanceProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_income: str = Field(pattern=r"^\d{1,8}(?:[.,]\d{1,2})?$")
    savings_goal: str = Field(pattern=r"^\d{1,8}(?:[.,]\d{1,2})?$")


class ReliabilitySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_mode: Literal["normal", "eco"]


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

    @router.get("/api/organizer/finance")
    async def finance(month: str = ""):
        try:
            return service.finance.summary(month or None)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/api/organizer/finance/query")
    async def finance_query(payload: FinanceQuery):
        try:
            return service.finance.summary(payload.month or None)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.put("/api/organizer/finance/budget")
    async def finance_budget(payload: FinanceBudgetUpdate):
        try:
            return service.finance.set_budget(payload.category, payload.monthly_limit)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.put("/api/organizer/finance/profile")
    async def finance_profile(payload: FinanceProfileUpdate):
        try:
            return service.finance.set_profile(**payload.model_dump())
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.get("/api/organizer/finance/export.csv")
    async def finance_export(month: str = ""):
        try:
            name, content = service.finance.csv_export(month or None)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @router.patch("/api/organizer/finance/transactions/{identifier}")
    async def update_finance_transaction(identifier: str, payload: FinanceTransactionUpdate):
        try:
            return service.finance.update(identifier, **payload.model_dump())
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/api/organizer/finance/rebuild")
    async def rebuild_finance(request: Request):
        require_local(request)
        return await service.mail.rebuild_recent_archive()

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

    @router.get("/api/organizer/calendar/events")
    async def calendar_events(start_at: str = "", end_at: str = ""):
        try:
            return service.calendar_events(start_at, end_at)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/organizer/calendar/events")
    async def create_event(payload: CalendarEventCreate):
        try:
            return await service.create_google_event(payload)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "No se pudo crear el evento en Google Calendar") from None

    @router.patch("/api/organizer/calendar/events")
    async def edit_event(request: Request, payload: CalendarEventEdit):
        try:
            return await service.edit_google_event(payload)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "No se pudo actualizar el evento en Google Calendar") from None

    @router.post("/api/organizer/calendar/events/delete")
    async def delete_event(payload: CalendarEventDelete):
        try:
            return await service.delete_google_event(payload.event_id, payload.etag)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "No se pudo eliminar el evento de Google Calendar") from None

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

    @router.get("/api/organizer/reliability")
    async def reliability(request: Request):
        require_local(request)
        return await asyncio.to_thread(service.reliability)

    @router.put("/api/organizer/reliability/settings")
    async def reliability_settings(request: Request, payload: ReliabilitySettingsUpdate):
        require_local(request)
        return service.set_resource_mode(payload.resource_mode)

    @router.post("/api/organizer/backups/{name}/verify")
    async def verify_backup(request: Request, name: str):
        require_local(request)
        try:
            return await asyncio.to_thread(service.recovery.verify, name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    return router
