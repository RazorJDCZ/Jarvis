from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, field_validator

from jarvis.capabilities.files import AttachmentError
from jarvis.capabilities.suite import CapabilitySuite


class ReminderCreateRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    due: str = Field(min_length=1, max_length=120)
    recurrence: str | None = Field(default="none", max_length=20)
    detail: str = Field(default="", max_length=2_000)

    @field_validator("title", "due")
    @classmethod
    def strip_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El valor no puede estar vac\u00edo")
        return value.strip()


class PermissionRequest(BaseModel):
    decision: str = Field(pattern=r"^(allow|ask)$")
    remote: bool = False
    expires_at: str | None = Field(default=None, max_length=80)


EffectiveSession = Callable[[Request, str], str]
LocalGuard = Callable[[Request], None]


def _trace_payload(record: Any) -> dict[str, object]:
    payload = asdict(record)
    payload["id"] = record.trace_id
    return payload


def create_capability_router(
    suite: CapabilitySuite,
    *,
    effective_session_id: EffectiveSession,
    require_local_console: LocalGuard,
    rememberable_actions: frozenset[str],
) -> APIRouter:
    router = APIRouter(prefix="/api")

    def session(request: Request, value: str) -> str:
        return effective_session_id(request, value)

    @router.get("/control-center")
    async def control_center(request: Request, session_id: str = "default"):
        return suite.dashboard(session(request, session_id))

    @router.get("/traces")
    async def traces(
        request: Request,
        session_id: str = "default",
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ):
        records = suite.traces.recent(session(request, session_id), limit)
        return {"traces": [_trace_payload(record) for record in records]}

    @router.get("/traces/{trace_id}")
    async def trace(request: Request, trace_id: str, session_id: str = "default"):
        record = suite.traces.get(trace_id, session(request, session_id))
        if record is None:
            raise HTTPException(status_code=404, detail="La traza no existe en esta sesi\u00f3n")
        return _trace_payload(record)

    @router.get("/attachments")
    async def attachments(request: Request, session_id: str = "default"):
        return {"attachments": suite.attachments.list(session(request, session_id))}

    @router.post("/attachments")
    async def upload_attachment(
        request: Request,
        file: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "default",
        source: Annotated[str, Form(max_length=40)] = "file",
    ):
        del source
        data = await file.read(suite.settings.attachment_max_bytes + 1)
        try:
            attachment = suite.attachments.save_bytes(
                session(request, session_id),
                file.filename,
                file.content_type or "application/octet-stream",
                data,
            )
        except AttachmentError as exc:
            status_code = 413 if "l\u00edmite" in str(exc) else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return {"attachment": attachment.public_dict()}

    @router.delete("/attachments/{attachment_id}")
    async def delete_attachment(
        request: Request,
        attachment_id: str,
        session_id: str = "default",
    ):
        try:
            removed = suite.attachments.delete(session(request, session_id), attachment_id)
        except AttachmentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": removed}

    @router.get("/reminders")
    async def reminders(request: Request, session_id: str = "default"):
        items = suite.reminders.list(session(request, session_id))
        return {
            "reminders": [
                {**asdict(item), "id": item.reminder_id, "status": "active"} for item in items
            ]
        }

    @router.post("/reminders")
    async def create_reminder(request: Request, payload: ReminderCreateRequest):
        recurrence = (payload.recurrence or "none").strip().casefold()
        try:
            due = suite.parse_due(payload.due, recurrence=recurrence)
            item = suite.reminders.create(
                session(request, payload.session_id),
                payload.title,
                due,
                recurrence,
                payload.detail,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"reminder": {**asdict(item), "id": item.reminder_id, "status": "active"}}

    @router.delete("/reminders/{reminder_id}")
    async def cancel_reminder(
        request: Request,
        reminder_id: str,
        session_id: str = "default",
    ):
        if not suite.reminders.cancel(reminder_id, session(request, session_id)):
            raise HTTPException(status_code=404, detail="El recordatorio no existe")
        return {"cancelled": True}

    @router.get("/notifications")
    async def notifications(
        request: Request,
        session_id: str = "default",
        consume: bool = False,
    ):
        return {
            "notifications": suite.notifications(
                session(request, session_id),
                consume=consume,
            )
        }

    @router.get("/system/metrics")
    async def system_metrics():
        snapshot, alerts = suite.system.sample()
        return {**asdict(snapshot), "alerts": [asdict(alert) for alert in alerts]}

    @router.get("/skills")
    async def skills():
        return {"skills": [asdict(item) for item in suite.skills.list()]}

    @router.get("/connectors")
    async def connectors():
        return {"connectors": await suite.connectors.statuses()}

    @router.get("/knowledge/sources")
    async def knowledge_sources(request: Request, session_id: str = "default"):
        items = suite.knowledge.list_sources(session(request, session_id))
        return {"sources": [asdict(item) for item in items]}

    @router.get("/knowledge/search")
    async def knowledge_search(
        request: Request,
        query: Annotated[str, Query(min_length=1, max_length=500)],
        session_id: str = "default",
    ):
        items = suite.knowledge.search(session(request, session_id), query)
        return {"results": [asdict(item) for item in items]}

    @router.get("/workspaces")
    async def workspaces():
        return {"workspaces": [{"name": item.name} for item in suite.developer.roots()]}

    @router.get("/permissions")
    async def permissions():
        return {"permissions": [asdict(item) for item in suite.permissions.list()]}

    @router.patch("/permissions/{action}")
    async def set_permission(request: Request, action: str, payload: PermissionRequest):
        require_local_console(request)
        if payload.remote:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Un permiso remoto solo puede recordarse al confirmarlo desde ese "
                    "dispositivo autenticado."
                ),
            )
        if action not in rememberable_actions:
            raise HTTPException(
                status_code=400,
                detail="Ese tipo de acci\u00f3n no admite permisos recordados.",
            )
        expires_at: datetime | str | None = payload.expires_at
        if payload.decision == "allow":
            maximum = datetime.now(UTC) + timedelta(days=30)
            if expires_at is None:
                expires_at = maximum
            else:
                try:
                    parsed_expiry = datetime.fromisoformat(
                        expires_at.strip().replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="La expiraci\u00f3n debe usar formato ISO 8601.",
                    ) from exc
                if parsed_expiry.tzinfo is None:
                    parsed_expiry = parsed_expiry.replace(tzinfo=UTC)
                if parsed_expiry.astimezone(UTC) > maximum:
                    raise HTTPException(
                        status_code=400,
                        detail="Un permiso recordado no puede superar 30 d\u00edas.",
                    )
                expires_at = parsed_expiry
        try:
            rule = suite.permissions.set(
                action,
                payload.remote,
                payload.decision,
                expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"permission": asdict(rule)}

    @router.delete("/permissions/{action}")
    async def delete_permission(request: Request, action: str, remote: bool = False):
        require_local_console(request)
        return {"deleted": suite.permissions.delete(action, remote)}

    @router.get("/games")
    async def games():
        try:
            items = suite._game_library().inventory()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"games": [asdict(item) for item in items]}

    return router


__all__ = ["create_capability_router"]
