from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from jarvis.services.memory import MemoryExtractor
from jarvis.services.preferences import Preferences, PreferenceStore


class MemoryEdit(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    updated_at: str = Field(min_length=1, max_length=80)


class NotificationAck(BaseModel):
    session_id: str = Field(default="default", min_length=1, max_length=128)
    identifiers: list[str] = Field(max_length=100)


def assistant_router(config, conversation, capabilities, effective_session_id, require_local):
    router = APIRouter(prefix="/api/assistant")
    preferences = PreferenceStore(config.data_dir / "preferences.json")

    @router.get("/preferences")
    async def get_preferences():
        return preferences.get().model_dump()

    @router.put("/preferences")
    async def set_preferences(request: Request, payload: Preferences):
        require_local(request)
        await asyncio.to_thread(preferences.save, payload)
        return payload.model_dump()

    @router.get("/memory")
    async def memory(request: Request):
        require_local(request)
        entries = await asyncio.to_thread(conversation.memory.store.list_entries, 500)
        profile = conversation.profile_store.load()
        # Both sources remain explicit; a learned memory does not silently rewrite the base profile.
        return {"memories": [asdict(item) for item in entries], "profile": asdict(profile)}

    @router.patch("/memory")
    async def edit_memory(request: Request, payload: MemoryEdit):
        require_local(request)
        if payload.content is not None and (
            not payload.content.strip() or MemoryExtractor.contains_sensitive_data(payload.content)
        ):
            raise HTTPException(400, "El recuerdo está vacío o contiene datos sensibles")
        changed = await asyncio.to_thread(
            conversation.memory.store.edit_entry,
            payload.key,
            payload.content,
            payload.updated_at,
        )
        if not changed:
            raise HTTPException(409, "El recuerdo cambió; actualiza la lista antes de editar")
        return {"saved": True}

    @router.get("/memory/export")
    async def export_memory(request: Request):
        require_local(request)
        return await memory(request)

    @router.patch("/profile")
    async def edit_profile(request: Request, payload: dict[str, str]):
        require_local(request)
        allowed = {
            "preferred_name",
            "location",
            "degree",
            "university",
            "academic_status",
            "work_context",
            "assistant_role",
            "future_vision",
        }
        if (
            not payload
            or set(payload) - allowed
            or any(
                len(v) > 500 or MemoryExtractor.contains_sensitive_data(v) for v in payload.values()
            )
        ):
            raise HTTPException(400, "Campo de perfil no permitido")
        path = conversation.profile_store.path
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(raw, dict):
                raise ValueError
            raw.update(payload)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.with_suffix(".backup.json").write_bytes(path.read_bytes())
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, "No se pudo actualizar el perfil") from exc
        return {"saved": True}

    @router.post("/notifications/ack")
    async def acknowledge(request: Request, payload: NotificationAck):
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        session = effective_session_id(request, payload.session_id)
        await asyncio.to_thread(capabilities.outbox.acknowledge, session, payload.identifiers)
        return {"acknowledged": True}

    @router.get("/briefing")
    async def briefing(request: Request, session_id: str = "default"):
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        session = effective_session_id(request, session_id)
        return await capabilities.briefing(session)

    @router.post("/knowledge/{source_id}/index")
    async def index_knowledge(request: Request, source_id: str, session_id: str = "default"):
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        session = effective_session_id(request, session_id)
        try:
            parts = await asyncio.to_thread(
                capabilities.knowledge.index_vectors, source_id, session
            )
        except Exception as exc:
            raise HTTPException(
                503, "No se pudo indexar; comprueba el modelo semántico local"
            ) from exc
        return {"fragments": parts}

    return router
