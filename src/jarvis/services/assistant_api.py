from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from jarvis.services.memory import MemoryExtractor
from jarvis.services.preferences import Preferences, PreferenceStore


class MemoryEdit(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    updated_at: str = Field(min_length=1, max_length=80)


class PersonalEntityInput(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    relation: str = Field(default="", max_length=160)
    details: str = Field(default="", max_length=1_000)
    expires_at: str | None = Field(default=None, max_length=80)
    updated_at: str | None = Field(default=None, max_length=80)


class AutomationInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    hour: int = Field(default=8, ge=0, le=23)
    lead_minutes: int = Field(default=30, ge=5, le=1_440)


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
        if capabilities is not None:
            briefing = next(
                (
                    rule
                    for rule in capabilities.automations.list()
                    if rule.rule_id == "morning-briefing"
                ),
                None,
            )
            if briefing is not None and briefing.hour != payload.briefing_hour:
                await asyncio.to_thread(
                    capabilities.automations.save,
                    rule_id=briefing.rule_id,
                    name=briefing.name,
                    kind=briefing.kind,
                    enabled=briefing.enabled,
                    hour=payload.briefing_hour,
                    lead_minutes=briefing.lead_minutes,
                )
        return payload.model_dump()

    @router.get("/automations")
    async def automations():
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        return {
            "rules": [asdict(rule) for rule in capabilities.automations.list()],
            "queue": capabilities.automations.job_stats(),
        }

    @router.post("/automations")
    async def create_automation(request: Request, payload: AutomationInput):
        require_local(request)
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        try:
            rule = await asyncio.to_thread(
                capabilities.automations.save, **payload.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"rule": asdict(rule)}

    @router.put("/automations/{rule_id}")
    async def update_automation(
        request: Request, rule_id: str, payload: AutomationInput
    ):
        require_local(request)
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        try:
            rule = await asyncio.to_thread(
                capabilities.automations.save,
                **payload.model_dump(),
                rule_id=rule_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"rule": asdict(rule)}

    @router.delete("/automations/{rule_id}")
    async def delete_automation(request: Request, rule_id: str):
        require_local(request)
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        if not await asyncio.to_thread(capabilities.automations.delete, rule_id):
            raise HTTPException(409, "La automatización base solo puede desactivarse")
        return {"deleted": True}

    @router.get("/weather")
    async def weather(location: str = ""):
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        try:
            return await capabilities.weather.current(location)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            raise HTTPException(503, "No se pudo consultar el clima") from None

    @router.get("/memory")
    async def memory(request: Request):
        require_local(request)
        entries = await asyncio.to_thread(conversation.memory.store.list_entries, 500)
        entities = await asyncio.to_thread(conversation.memory.store.list_entities, 500)
        profile = conversation.profile_store.load()
        # Both sources remain explicit; a learned memory does not silently rewrite the base profile.
        return {
            "memories": [asdict(item) for item in entries],
            "entities": [asdict(item) for item in entities],
            "profile": asdict(profile),
        }

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

    @router.post("/memory/entities")
    async def create_entity(request: Request, payload: PersonalEntityInput):
        require_local(request)
        try:
            entity = await asyncio.to_thread(
                conversation.memory.store.save_entity,
                payload.kind,
                payload.name,
                payload.relation,
                payload.details,
                expires_at=payload.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if entity is None:
            raise HTTPException(503, "No se pudo guardar la entidad personal")
        return {"entity": asdict(entity)}

    @router.put("/memory/entities/{entity_id}")
    async def update_entity(
        request: Request, entity_id: str, payload: PersonalEntityInput
    ):
        require_local(request)
        if payload.updated_at is None:
            raise HTTPException(400, "Falta la versión actual de la entidad")
        try:
            entity = await asyncio.to_thread(
                conversation.memory.store.save_entity,
                payload.kind,
                payload.name,
                payload.relation,
                payload.details,
                expires_at=payload.expires_at,
                entity_id=entity_id,
                expected_updated_at=payload.updated_at,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if entity is None:
            raise HTTPException(409, "La entidad cambió; actualiza la memoria antes de editar")
        return {"entity": asdict(entity)}

    @router.delete("/memory/entities/{entity_id}")
    async def delete_entity(request: Request, entity_id: str, updated_at: str):
        require_local(request)
        removed = await asyncio.to_thread(
            conversation.memory.store.delete_entity, entity_id, updated_at
        )
        if not removed:
            raise HTTPException(409, "La entidad cambió o ya no existe")
        return {"deleted": True}

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

    @router.get("/search")
    async def personal_search(
        request: Request,
        query: str = Query(min_length=1, max_length=300),
        session_id: str = Query(default="default", min_length=1, max_length=128),
    ):
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        session = effective_session_id(request, session_id)
        try:
            return await capabilities.personal_search.search(session, query)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/security")
    async def security_summary():
        if capabilities is None:
            raise HTTPException(503, "Capacidades desactivadas")
        rules = await asyncio.to_thread(capabilities.permissions.list)
        return {
            "local": {
                "trusted_medium_actions": bool(config.local_trusted_actions),
                "policy": (
                    "Las acciones de riesgo medio se ejecutan directamente en esta PC."
                    if config.local_trusted_actions
                    else "Las acciones de riesgo medio piden confirmación en esta PC."
                ),
            },
            "remote": {
                "read_only_direct": True,
                "medium_requires_confirmation": True,
                "high_always_requires_confirmation": True,
            },
            "screen_context_expires_seconds": 300,
            "file_search": {
                "read_only": True,
                "authorized_roots": len(config.configured_file_search_roots or ()),
            },
            "development": {
                "authorized_workspaces": sorted(config.configured_workspace_roots),
            },
            "remembered_permissions": [asdict(rule) for rule in rules],
        }

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
