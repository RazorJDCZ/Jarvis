from __future__ import annotations

import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from jarvis import __version__
from jarvis.config import Settings
from jarvis.providers.brain import build_brain
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS
from jarvis.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    TTSRequest,
    VoiceResponse,
)
from jarvis.services.conversation import ConversationService
from jarvis.services.wake import WakeGate
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


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    state_hub = StateHub()
    brain = build_brain(config)
    conversation = ConversationService(config, brain)
    transcriber = WhisperTranscriber(config)
    tts = PiperTTS(config)
    wake_gate = WakeGate(config.wake_word, config.wake_window_seconds, config.max_sessions)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        (config.data_dir / "tmp").mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title="Jarvis Local Core",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = config
    app.state.state_hub = state_hub
    app.state.conversation = conversation
    app.state.transcriber = transcriber
    app.state.tts = tts
    app.state.wake_gate = wake_gate
    trusted_origins = {
        f"http://127.0.0.1:{config.port}",
        f"http://localhost:{config.port}",
        f"http://[::1]:{config.port}",
        http_origin(config.host, config.port),
    }

    @app.middleware("http")
    async def secure_local_requests(request: Request, call_next) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin not in trusted_origins:
            return JSONResponse(status_code=403, content={"detail": "Origen no autorizado"})
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' ws:; img-src 'self' data:; "
            "media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), geolocation=(), microphone=(self), payment=(), usb=()"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

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
            wake_word=config.wake_word,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if not valid_session_id(request.session_id):
            raise HTTPException(status_code=400, detail="Identificador de sesion invalido")
        await state_hub.set("thinking", "Procesando solicitud")
        try:
            answer = await conversation.reply(request.session_id, request.message)
        except Exception as exc:
            await state_hub.set("error", "No pude generar una respuesta")
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await state_hub.set("ready", "Respuesta preparada")
        return ChatResponse(response=answer.text, provider=answer.provider)

    @app.delete("/api/conversation/{session_id}", status_code=204)
    async def reset_conversation(session_id: str) -> Response:
        if not valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Identificador de sesion invalido")
        conversation.reset(session_id)
        await state_hub.set("standby", "Conversacion reiniciada")
        return Response(status_code=204)

    @app.post("/api/voice/utterance", response_model=VoiceResponse)
    async def voice_utterance(
        audio: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "default",
        wake_mode: Annotated[bool, Form()] = False,
    ) -> VoiceResponse:
        if not valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Identificador de sesion invalido")
        audio_bytes = await audio.read(config.max_audio_bytes + 1)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="El audio esta vacio")
        if len(audio_bytes) > config.max_audio_bytes:
            raise HTTPException(status_code=413, detail="El audio supera el limite permitido")

        suffix = safe_audio_suffix(audio.filename)
        tmp_path: Path | None = None
        try:
            await state_hub.set("transcribing", "Convirtiendo voz en texto")
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                dir=config.data_dir / "tmp",
                delete=False,
            ) as tmp_file:
                tmp_file.write(audio_bytes)
                tmp_path = Path(tmp_file.name)

            transcript, language = await transcriber.transcribe(tmp_path)
            decision = wake_gate.evaluate(
                session_id=session_id,
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
            answer = await conversation.reply(session_id, decision.command)
            await state_hub.set("ready", "Respuesta preparada")
            return VoiceResponse(
                transcript=transcript,
                language=language,
                accepted=True,
                activated=decision.activated,
                response=answer.text,
                provider=answer.provider,
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
            audio_bytes = await tts.synthesize(request.text)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket("/ws")
    async def state_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in trusted_origins:
            await websocket.close(code=1008, reason="Origen no autorizado")
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
