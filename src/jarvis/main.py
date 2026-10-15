from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from jarvis import __version__
from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import ActionOutcome
from jarvis.capabilities.api import create_capability_router
from jarvis.config import Settings
from jarvis.providers.brain import build_brain
from jarvis.providers.codex_app_server import CodexAppServerClient
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS
from jarvis.providers.wake_detector import LightweightWakeDetector
from jarvis.schemas import (
    ActionDecisionRequest,
    ActionInfo,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    HealthResponse,
    InterruptResponse,
    RemoteAuthenticationRequest,
    RemoteCredentialRequest,
    RemoteRegistrationRequest,
    RemoteSessionRequest,
    RemoteStopRequest,
    TTSRequest,
    VoiceResponse,
)
from jarvis.services.conversation import ConversationService
from jarvis.services.feedback import FeedbackStore
from jarvis.services.interruptions import VoiceInterruptionMatcher
from jarvis.services.mail import MailService
from jarvis.services.mail_api import mail_router
from jarvis.services.organizer import Organizer
from jarvis.services.organizer_api import organizer_router
from jarvis.services.performance import PerformanceLog, available_ram_gb, response_events, stage
from jarvis.services.recovery import Recovery
from jarvis.services.remote_access import (
    RemoteAccessError,
    RemoteAccessService,
    RemoteDevice,
    RemoteIdentity,
)
from jarvis.services.wake import WakeGate
from jarvis.services.web_push import WebPush
from jarvis.state import StateHub

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_AUDIO_SUFFIXES = frozenset({".wav", ".webm", ".mp3", ".m4a", ".ogg", ".flac"})


def valid_session_id(value: str) -> bool:
    return _SESSION_ID_PATTERN.fullmatch(value) is not None


def safe_audio_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.casefold()
    return suffix if suffix in _AUDIO_SUFFIXES else ".audio"


def http_origin(host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{port}"


def action_info(outcome: ActionOutcome | None) -> ActionInfo | None:
    if outcome is None:
        return None
    return ActionInfo(
        action_id=outcome.action_id,
        name=outcome.name.value if outcome.name is not None else None,
        status=outcome.status.value,
        risk=outcome.risk.value if outcome.risk is not None else None,
        description=outcome.description,
        requires_confirmation=outcome.requires_confirmation,
        details=outcome.details,
    )


def _header_host(value: str) -> str:
    host = value.split(",", maxsplit=1)[0].strip()
    if host.startswith("["):
        return host.split("]", maxsplit=1)[0].lstrip("[").casefold()
    return host.split(":", maxsplit=1)[0].casefold()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    state_hub = StateHub()
    codex_client = CodexAppServerClient(config) if config.brain_mode in {"auto", "codex"} else None
    brain = build_brain(config, codex_client)
    action_engine = ActionEngine(config, codex_client=codex_client)
    conversation = ConversationService(config, brain, action_engine)
    transcriber = WhisperTranscriber(config)
    tts = PiperTTS(config)
    wake_gate = WakeGate(config.wake_word, config.wake_window_seconds, config.max_sessions)
    interruption_matcher = VoiceInterruptionMatcher(config.wake_word)
    remote_access = RemoteAccessService(config)
    feedback = FeedbackStore(config.data_dir / "agent-feedback.sqlite3")
    performance = PerformanceLog()
    wake_detector = LightweightWakeDetector(config.project_root / "models" / "wake")
    mail = MailService(config, action_engine.capabilities, codex_client)
    conversation.mail = mail
    organizer = Organizer(config, mail, action_engine.capabilities)
    organizer.recovery = Recovery(config)
    organizer.push = WebPush(organizer, remote_access)
    conversation.organizer = organizer
    if action_engine.capabilities is not None:
        action_engine.capabilities.mail = mail
        action_engine.capabilities.organizer = organizer

    async def warm_brain() -> bool:
        try:
            return await brain.warmup()
        except Exception:
            # Startup must remain usable when Codex is offline; AutoBrain will keep the
            # deterministic fallback available and the next chat can retry.
            return False

    async def preload_voice():
        if config.voice_preload and available_ram_gb() >= 3.5:
            try:
                await transcriber._ensure_model()
                await transcriber.park()
                if available_ram_gb() >= 2.5:
                    await tts.synthesize("Listo.")
            except Exception:
                pass

    async def resource_guard():
        from jarvis.services.performance import gpu_free_mb

        while True:
            await asyncio.sleep(15)
            if config.adaptive_resources:
                gpu_free = await asyncio.to_thread(gpu_free_mb)
                if available_ram_gb() < 1.8 or (gpu_free is not None and gpu_free < 512):
                    await brain.release()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        (config.data_dir / "tmp").mkdir(parents=True, exist_ok=True)
        await action_engine.start()
        await mail.start()
        await organizer.start()
        await organizer.push.start()
        voice_preload_task = asyncio.create_task(preload_voice())
        resource_task = asyncio.create_task(resource_guard())
        warmup_task = (
            asyncio.create_task(warm_brain(), name="jarvis-reasoning-warmup")
            if config.brain_mode in {"auto", "codex"}
            else None
        )
        try:
            yield
        finally:
            await organizer.push.close()
            await organizer.close()
            await mail.close()
            for background in (voice_preload_task, resource_task):
                background.cancel()
            await asyncio.gather(voice_preload_task, resource_task, return_exceptions=True)
            if warmup_task is not None:
                if not warmup_task.done():
                    warmup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await warmup_task
            close_brain = getattr(brain, "close", None)
            if callable(close_brain):
                await close_brain()
            else:
                await brain.release()
            await action_engine.close()
            await state_hub.close()

    app = FastAPI(
        title="Jarvis Hybrid Core",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = config
    app.state.brain = brain
    app.state.codex = codex_client
    app.state.state_hub = state_hub
    app.state.conversation = conversation
    app.state.transcriber = transcriber
    app.state.tts = tts
    app.state.wake_gate = wake_gate
    app.state.action_engine = action_engine
    app.state.remote_access = remote_access
    app.state.feedback = feedback
    app.state.performance = performance
    app.state.mail = mail
    app.state.organizer = organizer
    trusted_origins = {
        f"http://127.0.0.1:{config.port}",
        f"http://localhost:{config.port}",
        f"http://[::1]:{config.port}",
        http_origin(config.host, config.port),
    }
    if config.remote_access_enabled:
        trusted_origins.add(config.remote_origin)
    remote_open_api_paths = frozenset(
        {
            "/api/remote/status",
            "/api/remote/pair/options",
            "/api/remote/pair/verify",
            "/api/remote/auth/options",
            "/api/remote/auth/verify",
        }
    )

    def remote_identity(request: Request) -> RemoteIdentity | None:
        identity = getattr(request.state, "remote_identity", None)
        return identity if isinstance(identity, RemoteIdentity) else None

    def remote_device(request: Request) -> RemoteDevice | None:
        device = getattr(request.state, "remote_device", None)
        return device if isinstance(device, RemoteDevice) else None

    def require_local_console(request: Request) -> None:
        if getattr(request.state, "is_remote", False):
            raise HTTPException(
                status_code=403,
                detail="Esta operación solo está disponible desde la computadora de Jarvis.",
            )

    def require_remote_identity(request: Request) -> RemoteIdentity:
        identity = remote_identity(request)
        if identity is None:
            raise HTTPException(status_code=403, detail="Falta la identidad privada de Tailscale.")
        return identity

    def effective_session_id(request: Request, session_id: str) -> str:
        if not valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Identificador de sesion invalido")
        device = remote_device(request)
        if device is None:
            return session_id
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
        return f"remote:{device.device_id[:16]}:{digest}"

    if action_engine.capabilities is not None:
        app.include_router(
            create_capability_router(
                action_engine.capabilities,
                effective_session_id=effective_session_id,
                require_local_console=require_local_console,
                rememberable_actions=action_engine.rememberable_actions,
            )
        )

    def record_remote_result(
        request: Request,
        provider: str,
        outcome: ActionOutcome | None,
    ) -> None:
        device = remote_device(request)
        if device is None:
            return
        status = outcome.status.value if outcome is not None else "completed"
        summary = (
            outcome.name.value if outcome is not None and outcome.name is not None else provider
        )
        remote_access.record_event(device.device_id, "command", status, summary)

    from jarvis.services.assistant_api import assistant_router

    app.include_router(mail_router(mail, require_local_console, config.web_dir))
    app.include_router(
        organizer_router(organizer, require_local_console, effective_session_id, config.web_dir)
    )

    app.include_router(
        assistant_router(
            config,
            conversation,
            action_engine.capabilities,
            effective_session_id,
            require_local_console,
        )
    )

    @app.middleware("http")
    async def secure_local_requests(request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin not in trusted_origins:
            return JSONResponse(status_code=403, content={"detail": "Origen no autorizado"})
        identity = remote_access.identity_from_headers(request.headers)
        forwarded_host = _header_host(request.headers.get("x-forwarded-host", ""))
        request_host = _header_host(request.headers.get("host", ""))
        is_remote = bool(
            identity is not None
            or (
                config.remote_access_enabled
                and (
                    origin == config.remote_origin
                    or forwarded_host == config.remote_rp_id
                    or request_host == config.remote_rp_id
                )
            )
        )
        request.state.is_remote = is_remote
        request.state.remote_identity = identity
        request.state.remote_device = None
        if is_remote:
            if not config.remote_access_enabled:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "El acceso móvil está desactivado."},
                )
            if identity is None:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Tailscale no proporcionó una identidad válida."},
                )
            if request.method not in {"GET", "HEAD", "OPTIONS"} and origin != config.remote_origin:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "El origen remoto no coincide con Jarvis."},
                )
            device = remote_access.authenticate(
                request.cookies.get(remote_access.COOKIE_NAME),
                identity,
            )
            request.state.remote_device = device
            if (
                request.url.path.startswith("/api/")
                and request.url.path not in remote_open_api_paths
                and device is None
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Este dispositivo debe autenticarse con su passkey."},
                )
        if request.url.path in {
            "/api/chat",
            "/api/chat/stream",
            "/api/voice/utterance",
            "/api/voice/stream",
            "/api/voice/interrupt",
        }:
            mail.activity()
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' ws: wss:; img-src 'self' data: blob:; "
            "media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(self), geolocation=(), microphone=(self), payment=(), usb=()"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/" or request.url.path.startswith(
            ("/static/", "/service-worker.js", "/manifest.webmanifest")
        ):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        if is_remote and config.remote_cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def authenticated_response(payload: dict[str, object], token: str) -> JSONResponse:
        response = JSONResponse(payload)
        response.set_cookie(
            key=remote_access.COOKIE_NAME,
            value=token,
            max_age=config.remote_session_hours * 3_600,
            httponly=True,
            secure=config.remote_cookie_secure,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/remote/status")
    async def remote_status(request: Request):
        identity = remote_identity(request)
        device = remote_device(request)
        is_remote = bool(getattr(request.state, "is_remote", False))
        return {
            "enabled": config.remote_access_enabled,
            "remote": is_remote,
            "authenticated": not is_remote or device is not None,
            "remote_origin": config.remote_origin,
            "identity": (
                {"login": identity.login, "name": identity.name} if identity is not None else None
            ),
            "device": device.public_dict() if device is not None else None,
            "devices": remote_access.list_devices() if not is_remote else [],
            "passkey_available": config.remote_access_enabled and bool(config.remote_rp_id),
        }

    @app.post("/api/remote/pairing/start")
    async def start_remote_pairing(request: Request):
        require_local_console(request)
        try:
            return remote_access.start_pairing()
        except RemoteAccessError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/remote/pair/options")
    async def remote_pair_options(request: Request, payload: RemoteRegistrationRequest):
        identity = require_remote_identity(request)
        try:
            return remote_access.begin_registration(payload.code, payload.label, identity)
        except RemoteAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/remote/pair/verify")
    async def remote_pair_verify(request: Request, payload: RemoteCredentialRequest):
        identity = require_remote_identity(request)
        try:
            device, token = remote_access.finish_registration(
                payload.ceremony_id,
                dict(payload.credential),
                identity,
            )
        except RemoteAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return authenticated_response(
            {"authenticated": True, "device": device},
            token,
        )

    @app.post("/api/remote/auth/options")
    async def remote_auth_options(request: Request, payload: RemoteAuthenticationRequest):
        identity = require_remote_identity(request)
        try:
            return remote_access.begin_authentication(payload.device_id, identity)
        except RemoteAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/remote/auth/verify")
    async def remote_auth_verify(request: Request, payload: RemoteCredentialRequest):
        identity = require_remote_identity(request)
        try:
            device, token = remote_access.finish_authentication(
                payload.ceremony_id,
                dict(payload.credential),
                identity,
            )
        except RemoteAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return authenticated_response(
            {"authenticated": True, "device": device},
            token,
        )

    @app.post("/api/remote/logout")
    async def remote_logout(request: Request) -> JSONResponse:
        remote_access.logout(request.cookies.get(remote_access.COOKIE_NAME))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(
            remote_access.COOKIE_NAME,
            path="/",
            secure=config.remote_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/api/remote/devices")
    async def remote_devices(request: Request):
        require_local_console(request)
        return {"devices": remote_access.list_devices()}

    @app.delete("/api/remote/devices/{device_id}")
    async def revoke_remote_device(request: Request, device_id: str):
        require_local_console(request)
        if not re.fullmatch(r"[a-f0-9]{32}", device_id):
            raise HTTPException(status_code=400, detail="Identificador de dispositivo inválido")
        if not remote_access.revoke_device(device_id):
            raise HTTPException(status_code=404, detail="El dispositivo no está activo")
        return {"revoked": True}

    @app.get("/api/remote/activity")
    async def remote_activity(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 30):
        if getattr(request.state, "is_remote", False) and remote_device(request) is None:
            raise HTTPException(status_code=401, detail="Dispositivo no autenticado")
        return {"events": remote_access.recent_activity(limit)}

    @app.post("/api/remote/session")
    async def remote_session(request: Request, payload: RemoteSessionRequest):
        session_id = effective_session_id(request, payload.session_id)
        return {
            "state": state_hub.current,
            "action": action_info(action_engine.pending_for(session_id)),
        }

    @app.post("/api/remote/stop")
    async def remote_stop(request: Request, payload: RemoteStopRequest):
        session_id = effective_session_id(request, payload.session_id)
        cancelled = conversation.emergency_stop(session_id)
        wake_gate.reset(session_id)
        await state_hub.set("standby", "REMOTE_STOP")
        device = remote_device(request)
        if device is not None:
            remote_access.record_event(
                device.device_id,
                "emergency-stop",
                "completed",
                "Voz y acciones pendientes detenidas",
            )
        return {"stopped": True, **cancelled}

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        brain_status = await brain.status()
        return HealthResponse(
            status="ok",
            version=__version__,
            state=state_hub.current,
            brain=brain_status,
            stt=await transcriber.status(),
            tts=await tts.status(),
            actions=await action_engine.status(),
            vision=await action_engine.vision_status(),
            memory=conversation.memory.status(),
            wake_word=config.wake_word,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(http_request: Request, request: ChatRequest) -> ChatResponse:
        session_id = effective_session_id(http_request, request.session_id)
        await state_hub.set("thinking", "Interpretando intención y seleccionando herramientas")
        try:
            with stage("conversation"):
                answer = await conversation.reply(
                    session_id,
                    request.message,
                    remote=remote_device(http_request) is not None,
                    attachment_ids=tuple(request.attachment_ids),
                )
        except Exception as exc:
            await state_hub.set("error", "No pude generar una respuesta")
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await state_hub.set(
            "ready",
            "Acción verificada" if answer.action is not None else "Respuesta preparada",
        )
        record_remote_result(http_request, answer.provider, answer.action)
        return ChatResponse(
            response=answer.text,
            provider=answer.provider,
            action=action_info(answer.action),
            trace_id=answer.trace_id,
        )

    @app.post("/api/feedback", status_code=204)
    async def agent_feedback(http_request: Request, request: FeedbackRequest) -> Response:
        session_id = effective_session_id(http_request, request.session_id)
        feedback.record(
            request.trace_id,
            session_id,
            request.rating,
            category=request.category,
            note=request.note,
        )
        return Response(status_code=204)

    @app.post("/api/chat/stream")
    async def chat_stream(http_request: Request, request: ChatRequest):
        session = effective_session_id(http_request, request.session_id)
        return StreamingResponse(
            response_events(lambda: chat(http_request, request), performance, session),
            media_type="application/x-ndjson",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    @app.get("/api/performance")
    async def performance_status(request: Request, session_id: str = "default"):
        return {
            "requests": performance.recent(effective_session_id(request, session_id)),
            "available_ram_gb": round(available_ram_gb(), 2),
            "lightweight_wake": wake_detector.available,
        }

    @app.post("/api/actions/decision", response_model=ChatResponse)
    async def decide_action(http_request: Request, request: ActionDecisionRequest) -> ChatResponse:
        session_id = effective_session_id(http_request, request.session_id)
        await state_hub.set("thinking", "Aplicando decisión de seguridad")
        answer = await conversation.decide_action(
            session_id,
            request.action_id,
            request.approve,
            request.choice,
            request.remember,
        )
        await state_hub.set("ready", "Decisión procesada")
        record_remote_result(http_request, answer.provider, answer.action)
        return ChatResponse(
            response=answer.text,
            provider=answer.provider,
            action=action_info(answer.action),
            trace_id=answer.trace_id,
        )

    @app.get("/api/actions/audit")
    async def action_audit(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ):
        require_local_console(request)
        return {"entries": action_engine.recent_audit(limit)}

    @app.delete("/api/conversation/{session_id}", status_code=204)
    async def reset_conversation(request: Request, session_id: str) -> Response:
        effective_session = effective_session_id(request, session_id)
        conversation.reset(effective_session)
        await state_hub.set("standby", "Conversacion reiniciada")
        return Response(status_code=204)

    @app.post("/api/organizer/transcribe")
    async def transcribe_capture(audio: Annotated[UploadFile, File()]):
        content = await audio.read(config.max_audio_bytes + 1)
        if not content or len(content) > config.max_audio_bytes:
            raise HTTPException(413, "Audio vacío o demasiado grande")
        mail.activity()
        temporary = config.data_dir / "tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=safe_audio_suffix(audio.filename), dir=temporary, delete=False
        ) as f:
            f.write(content)
            path = Path(f.name)
        try:
            text, _ = await transcriber.transcribe(path)
            return {"text": text[:2000]}
        except Exception:
            raise HTTPException(503, "No se pudo transcribir. Puedes escribir la captura") from None
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/voice/utterance", response_model=VoiceResponse)
    async def voice_utterance(
        request: Request,
        audio: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "default",
        wake_mode: Annotated[bool, Form()] = False,
        wake_fast: Annotated[bool, Form()] = False,
    ) -> VoiceResponse:
        effective_session = effective_session_id(request, session_id)
        audio_bytes = await audio.read(config.max_audio_bytes + 1)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="El audio esta vacio")
        if len(audio_bytes) > config.max_audio_bytes:
            raise HTTPException(status_code=413, detail="El audio supera el limite permitido")

        suffix = safe_audio_suffix(audio.filename)
        tmp_path: Path | None = None
        try:
            if wake_mode and wake_fast and not wake_gate.is_armed(effective_session):
                with stage("wake_detection"):
                    detected = await wake_detector.detects(audio_bytes)
                if detected is False:
                    return VoiceResponse(transcript="")
            await state_hub.set("transcribing", "Preparando memoria para reconocer tu voz")
            if not config.adaptive_resources or available_ram_gb() < config.model_reserve_gb:
                with stage("model_release"):
                    await brain.release()
            await state_hub.set("transcribing", "Convirtiendo voz en texto")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                dir=config.data_dir / "tmp",
                delete=False,
            ) as tmp_file:
                tmp_file.write(audio_bytes)
                tmp_path = Path(tmp_file.name)

            with stage("transcription"):
                transcript, language = await transcriber.transcribe(tmp_path)
            decision = wake_gate.evaluate(
                session_id=effective_session,
                transcript=transcript,
                require_wake_word=wake_mode,
            )
            if not decision.accepted:
                await state_hub.set("standby", f"En espera de '{config.wake_word}'")
                return VoiceResponse(transcript=transcript, language=language)
            if decision.needs_command:
                await state_hub.set("listening", "Te escucho")
                return VoiceResponse(
                    transcript=transcript,
                    language=language,
                    accepted=True,
                    activated=True,
                    needs_command=True,
                    response="Te escucho.",
                )

            await state_hub.set("thinking", "Preparando respuesta")
            answer = await conversation.reply(
                effective_session,
                decision.command,
                remote=remote_device(request) is not None,
            )
            await state_hub.set("ready", "Respuesta preparada")
            record_remote_result(request, answer.provider, answer.action)
            return VoiceResponse(
                transcript=transcript,
                language=language,
                accepted=True,
                activated=decision.activated,
                response=answer.text,
                provider=answer.provider,
                action=action_info(answer.action),
                trace_id=answer.trace_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            await state_hub.set("error", "Fallo en el pipeline de voz")
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    @app.post("/api/tts")
    async def synthesize(request: TTSRequest) -> Response:
        try:
            with stage("tts"):
                audio_bytes = await tts.synthesize(request.text)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/voice/stream")
    async def voice_stream(
        request: Request,
        audio: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "default",
        wake_mode: Annotated[bool, Form()] = False,
        wake_fast: Annotated[bool, Form()] = False,
    ):
        session = effective_session_id(request, session_id)
        # Read while the UploadFile is owned by this request, before response streaming.
        import io

        data = await audio.read(config.max_audio_bytes + 1)
        if not data or len(data) > config.max_audio_bytes:
            raise HTTPException(status_code=413, detail="Tamaño de audio no permitido")
        owned_audio = UploadFile(io.BytesIO(data), filename=audio.filename)
        return StreamingResponse(
            response_events(
                lambda: voice_utterance(request, owned_audio, session_id, wake_mode, wake_fast),
                performance,
                session,
            ),
            media_type="application/x-ndjson",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    @app.post("/api/voice/interrupt", response_model=InterruptResponse)
    async def interrupt_voice(
        request: Request,
        audio: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "default",
    ) -> InterruptResponse:
        effective_session_id(request, session_id)
        audio_bytes = await audio.read(config.max_audio_bytes + 1)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="El audio esta vacio")
        if len(audio_bytes) > config.max_audio_bytes:
            raise HTTPException(status_code=413, detail="El audio supera el limite permitido")
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=safe_audio_suffix(audio.filename),
                dir=config.data_dir / "tmp",
                delete=False,
            ) as tmp_file:
                tmp_file.write(audio_bytes)
                tmp_path = Path(tmp_file.name)
            transcript, language = await transcriber.transcribe(tmp_path)
            return InterruptResponse(
                transcript=transcript,
                language=language,
                interrupted=interruption_matcher.matches(transcript),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    @app.websocket("/ws")
    async def state_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in trusted_origins:
            await websocket.close(code=1008, reason="Origen no autorizado")
            return
        identity = remote_access.identity_from_headers(websocket.headers)
        forwarded_host = _header_host(websocket.headers.get("x-forwarded-host", ""))
        request_host = _header_host(websocket.headers.get("host", ""))
        is_remote = bool(
            identity is not None
            or (
                config.remote_access_enabled
                and (
                    origin == config.remote_origin
                    or forwarded_host == config.remote_rp_id
                    or request_host == config.remote_rp_id
                )
            )
        )
        if is_remote and (
            not config.remote_access_enabled
            or identity is None
            or remote_access.authenticate(
                websocket.cookies.get(remote_access.COOKIE_NAME),
                identity,
            )
            is None
        ):
            await websocket.close(code=1008, reason="Dispositivo remoto no autenticado")
            return
        await state_hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            await state_hub.disconnect(websocket)

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        return FileResponse(config.web_dir / "manifest.webmanifest")

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        return FileResponse(
            config.web_dir / "service-worker.js",
            media_type="application/javascript",
        )

    app.mount("/static", StaticFiles(directory=config.web_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(config.web_dir / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = Settings()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    run()
