from __future__ import annotations

import re
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
    attachment_ids: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("message")
    @classmethod
    def message_must_have_content(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("El mensaje no puede estar vacio")
        return clean_value

    @field_validator("attachment_ids")
    @classmethod
    def attachment_ids_must_be_opaque(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[a-f0-9]{32}", item) for item in value):
            raise ValueError("Los adjuntos deben usar identificadores opacos v\u00e1lidos")
        return list(dict.fromkeys(value))


class ActionInfo(BaseModel):
    action_id: str | None = None
    name: str | None = None
    status: str
    risk: str | None = None
    description: str | None = None
    requires_confirmation: bool = False
    details: dict[str, object] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    response: str
    provider: str
    action: ActionInfo | None = None
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    rating: Literal[-1, 1]
    category: str = Field(default="general", min_length=1, max_length=40)
    note: str = Field(default="", max_length=500)


class ActionDecisionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    action_id: str = Field(min_length=1, max_length=64)
    approve: bool | None = None
    remember: bool = False
    choice: str | None = Field(default=None, min_length=1, max_length=120)


class RemoteRegistrationRequest(BaseModel):
    code: str = Field(min_length=8, max_length=12)
    label: str = Field(min_length=2, max_length=80)

    @field_validator("code", "label")
    @classmethod
    def remote_text_must_have_content(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("El valor no puede estar vacío")
        return clean_value


class RemoteAuthenticationRequest(BaseModel):
    device_id: str = Field(min_length=32, max_length=64, pattern=r"^[a-f0-9]+$")


class RemoteCredentialRequest(BaseModel):
    ceremony_id: str = Field(min_length=32, max_length=64, pattern=r"^[a-f0-9]+$")
    credential: dict[str, object]


class RemoteStopRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


class RemoteSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


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
    action: ActionInfo | None = None


class InterruptResponse(BaseModel):
    transcript: str
    language: str
    interrupted: bool


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
    actions: ProviderStatus
    vision: ProviderStatus
    memory: ProviderStatus
    wake_word: str
