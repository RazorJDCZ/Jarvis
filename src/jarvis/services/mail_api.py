from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.capabilities.connectors import ConnectorError
from jarvis.services.mail_providers import MailError


class ClientSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["google", "microsoft"]
    client_id: str = Field(min_length=10, max_length=250)
    client_secret: str = Field(default="", max_length=300)


class MailUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["review", "reply", "waiting", "resolved"]
    snooze_hours: int | None = Field(default=None, ge=0, le=720)
    draft: str | None = Field(default=None, max_length=3000)
    version: str | None = Field(default=None, max_length=2000)


class MailSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=50)


class ReplyAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=3000)
    version: str = Field(min_length=1, max_length=2000)


class ReplySend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization: str = Field(min_length=32, max_length=200)
    body: str = Field(min_length=1, max_length=3000)


def mail_router(service, require_local, web_dir):
    router = APIRouter()

    @router.get("/mail")
    async def page():
        return FileResponse(web_dir / "mail.html", headers={"Cache-Control": "no-store"})

    @router.get("/api/mail/status")
    async def status():
        return service.status()

    @router.get("/api/mail/items")
    async def items(include_resolved: bool = False):
        return {"items": service.store.list(include_resolved)}

    @router.post("/api/mail/search")
    async def search(payload: MailSearch):
        try:
            return service.search(payload.query, payload.limit)
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.put("/api/mail/config")
    async def configure(request: Request, payload: ClientSettings):
        require_local(request)
        try:
            service.configure(
                payload.provider, payload.client_id.strip(), payload.client_secret.strip()
            )
        except (MailError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from None
        return {"saved": True}

    @router.post("/api/mail/connect/{provider}")
    async def connect(request: Request, provider: Literal["google", "microsoft"]):
        require_local(request)
        try:
            return {"url": await service.begin_auth(provider)}
        except MailError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.delete("/api/mail/accounts/{identifier}")
    async def disconnect(request: Request, identifier: str):
        require_local(request)
        async with service.lock:
            service.store.disconnect(identifier)
        return {"disconnected": True}

    @router.post("/api/mail/sync")
    async def sync(request: Request):
        require_local(request)
        service.request_sync()
        return {"queued": True}

    def find(identifier):
        item = service.store.get(identifier)
        if not item:
            raise HTTPException(404, "El correo ya no está disponible")
        return item

    @router.patch("/api/mail/items/{identifier}")
    async def update(request: Request, identifier: str, payload: MailUpdate):
        require_local(request)
        item = find(identifier)
        if payload.version is not None and item["version"] != payload.version:
            raise HTTPException(409, "Llegó un mensaje nuevo; actualiza antes de guardar")
        values = {"state": payload.state}
        if payload.snooze_hours is not None:
            values["snoozed_until"] = (
                time.time() + payload.snooze_hours * 3600 if payload.snooze_hours else 0
            )
        if payload.draft is not None:
            values["draft"] = payload.draft
        service.store.update(identifier, **values)
        return {"saved": True}

    @router.post("/api/mail/items/{identifier}/task")
    async def task(request: Request, identifier: str):
        require_local(request)
        find(identifier)
        try:
            return await service.create_task(identifier)
        except (MailError, ConnectorError) as exc:
            raise HTTPException(503, str(exc)) from None

    @router.post("/api/mail/items/{identifier}/draft")
    async def draft(request: Request, identifier: str):
        require_local(request)
        find(identifier)
        try:
            return await service.draft(identifier)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "Codex Luna no pudo preparar el borrador") from None

    @router.post("/api/mail/items/{identifier}/reply/authorize")
    async def authorize_reply(request: Request, identifier: str, payload: ReplyAuthorization):
        require_local(request)
        find(identifier)
        try:
            return service.authorize_reply(identifier, payload.body, payload.version)
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/api/mail/items/{identifier}/reply/send")
    async def send_reply(request: Request, identifier: str, payload: ReplySend):
        require_local(request)
        find(identifier)
        try:
            result = await service.send_authorized_reply(
                payload.authorization, payload.body, identifier
            )
        except MailError as exc:
            raise HTTPException(409, str(exc)) from None
        return result

    return router
