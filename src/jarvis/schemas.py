from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

JarvisState = Literal[
    "standby",
    "listening",
    "transcribing",
    "thinking",
    "speaking",
    "ready",
    "error",
]


class StateSnapshot(BaseModel):
    state: JarvisState = "standby"
    detail: str = "En espera"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)

    @field_validator("message")
    @classmethod
    def message_must_have_content(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("El mensaje no puede estar vacio")
        return clean_value


class ChatResponse(BaseModel):
    response: str
    provider: str


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)

    @field_validator("text")
    @classmethod
    def text_must_have_content(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("El texto no puede estar vacio")
        return clean_value


class VoiceResponse(BaseModel):
    transcript: str
    language: str | None = None
    accepted: bool = False
    activated: bool = False
    needs_command: bool = False
    response: str | None = None
    provider: str | None = None


class ProviderStatus(BaseModel):
    available: bool
    name: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    version: str
    state: StateSnapshot
    brain: ProviderStatus
    stt: ProviderStatus
    tts: ProviderStatus
    wake_word: str
