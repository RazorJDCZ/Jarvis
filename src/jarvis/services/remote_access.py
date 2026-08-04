from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from jarvis.config import Settings


class RemoteAccessError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RemoteIdentity:
    login: str
    name: str


@dataclass(frozen=True, slots=True)
class RemoteDevice:
    device_id: str
    label: str
    login: str
    display_name: str
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: tuple[str, ...]
    created_at: float
    last_seen_at: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "label": self.label,
            "login": self.login,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
        }


@dataclass(frozen=True, slots=True)
class PairingChallenge:
    code_hash: bytes
    expires_at: float


@dataclass(frozen=True, slots=True)
class RegistrationCeremony:
    challenge: bytes
    identity: RemoteIdentity
    label: str
    code_hash: bytes
    expires_at: float


@dataclass(frozen=True, slots=True)
class AuthenticationCeremony:
    challenge: bytes
    device_id: str
    identity: RemoteIdentity
    expires_at: float


@dataclass(frozen=True, slots=True)
class RemoteSession:
    device_id: str
    login: str
    expires_at: float


class RemoteAccessService:
    """Passkey-backed second factor for traffic already authenticated by Tailscale."""

    COOKIE_NAME = "jarvis_remote_session"
    _CEREMONY_SECONDS = 120
    _MAX_FAILED_CODES = 5
    _MAX_SESSIONS = 64

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.remote_access_enabled
        self.path = settings.remote_database_path
        self._lock = threading.RLock()
        self._pairing_pepper = secrets.token_bytes(32)
        self._pairing: PairingChallenge | None = None
        self._registrations: OrderedDict[str, RegistrationCeremony] = OrderedDict()
        self._authentications: OrderedDict[str, AuthenticationCeremony] = OrderedDict()
        self._sessions: OrderedDict[str, RemoteSession] = OrderedDict()
        self._failed_codes: dict[str, list[float]] = {}
        if self.enabled:
            self._initialize()

    @staticmethod
    def identity_from_headers(headers: Mapping[str, str]) -> RemoteIdentity | None:
        login = headers.get("tailscale-user-login", "").strip()
        if not login:
            return None
        name = headers.get("tailscale-user-name", "").strip() or login
        if (
            len(login) > 320
            or len(name) > 200
            or any(character in login + name for character in "\r\n\0")
        ):
            return None
        return RemoteIdentity(login=login.casefold(), name=name)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS remote_devices (
                    device_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    login TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    credential_id BLOB NOT NULL UNIQUE,
                    public_key BLOB NOT NULL,
                    sign_count INTEGER NOT NULL,
                    transports TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_remote_devices_login
                    ON remote_devices(login, revoked);

                CREATE TABLE IF NOT EXISTS remote_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS remote_activity (
                    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RemoteAccessError("El acceso móvil todavía no está habilitado.")

    def _metadata(self, key: str) -> str:
        if not self.enabled:
            return ""
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM remote_metadata WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row is not None else ""

    def _set_metadata(self, key: str, value: str) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO remote_metadata(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _owner_login(self) -> str:
        return self.settings.remote_allowed_login.casefold() or self._metadata("owner_login")

    def _require_identity_allowed(self, identity: RemoteIdentity) -> None:
        allowed = self._owner_login()
        if allowed and not hmac.compare_digest(identity.login, allowed):
            raise RemoteAccessError("Esta identidad de Tailscale no está autorizada.")

    def _hash_code(self, digits: str) -> bytes:
        return hmac.new(self._pairing_pepper, digits.encode("ascii"), hashlib.sha256).digest()

    @staticmethod
    def _clean_code(code: str) -> str:
        return "".join(character for character in code if character.isdigit())

    @staticmethod
    def _clean_label(label: str) -> str:
        cleaned = " ".join(label.split()).strip()
        if not 2 <= len(cleaned) <= 80 or any(character in cleaned for character in "\r\n\0"):
            raise RemoteAccessError("El nombre del dispositivo no es válido.")
        return cleaned

    def _prune(self, now: float | None = None) -> None:
        current = time.time() if now is None else now
        if self._pairing is not None and current > self._pairing.expires_at:
            self._pairing = None
        for ceremonies in (self._registrations, self._authentications):
            expired = [
                ceremony_id
                for ceremony_id, ceremony in ceremonies.items()
                if current > ceremony.expires_at
            ]
            for ceremony_id in expired:
                ceremonies.pop(ceremony_id, None)
        expired_sessions = [
            token_hash
            for token_hash, session in self._sessions.items()
            if current > session.expires_at
        ]
        for token_hash in expired_sessions:
            self._sessions.pop(token_hash, None)
        for login, attempts in tuple(self._failed_codes.items()):
            recent = [attempt for attempt in attempts if current - attempt <= 300]
            if recent:
                self._failed_codes[login] = recent
            else:
                self._failed_codes.pop(login, None)

    def start_pairing(self) -> dict[str, Any]:
        self._require_enabled()
        now = time.time()
        digits = f"{secrets.randbelow(100_000_000):08d}"
        self._pairing = PairingChallenge(
            code_hash=self._hash_code(digits),
            expires_at=now + self.settings.remote_pairing_seconds,
        )
        self._registrations.clear()
        return {
            "code": f"{digits[:4]}-{digits[4:]}",
            "expires_at": self._pairing.expires_at,
            "remote_origin": self.settings.remote_origin,
        }

    def _record_failed_code(self, identity: RemoteIdentity) -> None:
        now = time.time()
        attempts = self._failed_codes.setdefault(identity.login, [])
        attempts.append(now)
        if len([attempt for attempt in attempts if now - attempt <= 300]) >= self._MAX_FAILED_CODES:
            self._pairing = None
            raise RemoteAccessError(
                "Demasiados intentos de emparejamiento. Genera un código nuevo desde la PC."
            )

    def begin_registration(
        self,
        code: str,
        label: str,
        identity: RemoteIdentity,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._require_identity_allowed(identity)
        self._prune()
        digits = self._clean_code(code)
        candidate_hash = self._hash_code(digits) if len(digits) == 8 else b""
        if (
            self._pairing is None
            or not candidate_hash
            or not hmac.compare_digest(candidate_hash, self._pairing.code_hash)
        ):
            self._record_failed_code(identity)
            raise RemoteAccessError("El código de emparejamiento es inválido o expiró.")
        self._failed_codes.pop(identity.login, None)
        clean_label = self._clean_label(label)
        challenge = secrets.token_bytes(32)
        ceremony_id = uuid4().hex
        existing = [
            PublicKeyCredentialDescriptor(
                id=device.credential_id,
                transports=self._transport_enums(device.transports),
            )
            for device in self.list_devices(include_private=True)
            if device.login == identity.login
        ]
        options = generate_registration_options(
            rp_id=self.settings.remote_rp_id,
            rp_name="Jarvis Local Core",
            user_id=hashlib.sha256(identity.login.encode("utf-8")).digest(),
            user_name=identity.login,
            user_display_name=identity.name,
            challenge=challenge,
            timeout=self._CEREMONY_SECONDS * 1_000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=existing,
        )
        self._registrations[ceremony_id] = RegistrationCeremony(
            challenge=challenge,
            identity=identity,
            label=clean_label,
            code_hash=candidate_hash,
            expires_at=time.time() + self._CEREMONY_SECONDS,
        )
        self._limit_ceremonies(self._registrations)
        return {"ceremony_id": ceremony_id, "options": json.loads(options_to_json(options))}

    def finish_registration(
        self,
        ceremony_id: str,
        credential: dict[str, Any],
        identity: RemoteIdentity,
    ) -> tuple[dict[str, Any], str]:
        self._require_enabled()
        self._prune()
        ceremony = self._registrations.pop(ceremony_id, None)
        if ceremony is None or ceremony.identity.login != identity.login:
            raise RemoteAccessError("El emparejamiento expiró o no pertenece a este dispositivo.")
        if self._pairing is None or not hmac.compare_digest(
            ceremony.code_hash,
            self._pairing.code_hash,
        ):
            raise RemoteAccessError("El código de emparejamiento ya no está activo.")
        try:
            verification = verify_registration_response(
                credential=credential,
                expected_challenge=ceremony.challenge,
                expected_rp_id=self.settings.remote_rp_id,
                expected_origin=self.settings.remote_origin,
                require_user_verification=True,
            )
        except (InvalidRegistrationResponse, ValueError, TypeError) as exc:
            raise RemoteAccessError("La passkey no pudo verificarse.") from exc
        now = time.time()
        device_id = uuid4().hex
        transports = self._credential_transports(credential)
        try:
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO remote_devices(
                        device_id, label, login, display_name, credential_id, public_key,
                        sign_count, transports, created_at, last_seen_at, revoked
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        device_id,
                        ceremony.label,
                        identity.login,
                        identity.name,
                        verification.credential_id,
                        verification.credential_public_key,
                        verification.sign_count,
                        json.dumps(transports),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RemoteAccessError(
                "Esta passkey ya pertenece a un dispositivo emparejado."
            ) from exc
        if not self._metadata("owner_login"):
            self._set_metadata("owner_login", identity.login)
        self._pairing = None
        token = self._new_session(device_id, identity.login)
        self.record_event(device_id, "pairing", "completed", "Dispositivo emparejado con passkey")
        device = self.get_device(device_id)
        if device is None:
            raise RemoteAccessError("El dispositivo no pudo guardarse.")
        return device.public_dict(), token

    def begin_authentication(
        self,
        device_id: str,
        identity: RemoteIdentity,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._require_identity_allowed(identity)
        self._prune()
        device = self.get_device(device_id)
        if device is None or device.login != identity.login:
            raise RemoteAccessError("El dispositivo no está emparejado con esta identidad.")
        challenge = secrets.token_bytes(32)
        ceremony_id = uuid4().hex
        options = generate_authentication_options(
            rp_id=self.settings.remote_rp_id,
            challenge=challenge,
            timeout=self._CEREMONY_SECONDS * 1_000,
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=device.credential_id,
                    transports=self._transport_enums(device.transports),
                )
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        self._authentications[ceremony_id] = AuthenticationCeremony(
            challenge=challenge,
            device_id=device_id,
            identity=identity,
            expires_at=time.time() + self._CEREMONY_SECONDS,
        )
        self._limit_ceremonies(self._authentications)
        return {"ceremony_id": ceremony_id, "options": json.loads(options_to_json(options))}

    def finish_authentication(
        self,
        ceremony_id: str,
        credential: dict[str, Any],
        identity: RemoteIdentity,
    ) -> tuple[dict[str, Any], str]:
        self._require_enabled()
        self._prune()
        ceremony = self._authentications.pop(ceremony_id, None)
        if ceremony is None or ceremony.identity.login != identity.login:
            raise RemoteAccessError("La autenticación expiró o pertenece a otro dispositivo.")
        device = self.get_device(ceremony.device_id)
        if device is None or device.login != identity.login:
            raise RemoteAccessError("El dispositivo ya no está autorizado.")
        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=ceremony.challenge,
                expected_rp_id=self.settings.remote_rp_id,
                expected_origin=self.settings.remote_origin,
                credential_public_key=device.public_key,
                credential_current_sign_count=device.sign_count,
                require_user_verification=True,
            )
        except (InvalidAuthenticationResponse, ValueError, TypeError) as exc:
            self.record_event(device.device_id, "authentication", "rejected", "Passkey rechazada")
            raise RemoteAccessError("La passkey no pudo verificarse.") from exc
        now = time.time()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE remote_devices
                SET sign_count = ?, last_seen_at = ?
                WHERE device_id = ? AND revoked = 0
                """,
                (verification.new_sign_count, now, device.device_id),
            )
        token = self._new_session(device.device_id, identity.login)
        self.record_event(device.device_id, "authentication", "completed", "Passkey verificada")
        refreshed = self.get_device(device.device_id)
        if refreshed is None:
            raise RemoteAccessError("El dispositivo dejó de estar autorizado.")
        return refreshed.public_dict(), token

    @staticmethod
    def _credential_transports(credential: dict[str, Any]) -> tuple[str, ...]:
        response = credential.get("response")
        raw = response.get("transports", []) if isinstance(response, dict) else []
        allowed = {transport.value for transport in AuthenticatorTransport}
        return tuple(
            transport
            for transport in raw[:8]
            if isinstance(transport, str) and transport in allowed
        )

    @staticmethod
    def _transport_enums(transports: tuple[str, ...]) -> list[AuthenticatorTransport]:
        allowed = {transport.value: transport for transport in AuthenticatorTransport}
        return [allowed[transport] for transport in transports if transport in allowed]

    @staticmethod
    def _limit_ceremonies(ceremonies: OrderedDict[str, Any]) -> None:
        while len(ceremonies) > 16:
            ceremonies.popitem(last=False)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()

    def _new_session(self, device_id: str, login: str) -> str:
        token = secrets.token_urlsafe(48)
        token_hash = self._token_hash(token)
        self._sessions[token_hash] = RemoteSession(
            device_id=device_id,
            login=login,
            expires_at=time.time() + self.settings.remote_session_hours * 3_600,
        )
        self._sessions.move_to_end(token_hash)
        while len(self._sessions) > self._MAX_SESSIONS:
            self._sessions.popitem(last=False)
        return token

    def authenticate(
        self,
        token: str | None,
        identity: RemoteIdentity,
    ) -> RemoteDevice | None:
        if not token or not self.enabled:
            return None
        self._prune()
        session = self._sessions.get(self._token_hash(token))
        if session is None or not hmac.compare_digest(session.login, identity.login):
            return None
        device = self.get_device(session.device_id)
        if device is None or device.login != identity.login:
            return None
        return device

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(self._token_hash(token), None)

    def get_device(self, device_id: str) -> RemoteDevice | None:
        if not self.enabled:
            return None
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT * FROM remote_devices
                WHERE device_id = ? AND revoked = 0
                """,
                (device_id,),
            ).fetchone()
        return self._device_from_row(row) if row is not None else None

    def list_devices(self, *, include_private: bool = False) -> list[Any]:
        if not self.enabled:
            return []
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM remote_devices
                WHERE revoked = 0
                ORDER BY created_at ASC
                """
            ).fetchall()
        devices = [self._device_from_row(row) for row in rows]
        return devices if include_private else [device.public_dict() for device in devices]

    @staticmethod
    def _device_from_row(row: sqlite3.Row) -> RemoteDevice:
        try:
            raw_transports = json.loads(row["transports"])
        except (json.JSONDecodeError, TypeError):
            raw_transports = []
        transports = tuple(item for item in raw_transports if isinstance(item, str))
        return RemoteDevice(
            device_id=str(row["device_id"]),
            label=str(row["label"]),
            login=str(row["login"]),
            display_name=str(row["display_name"]),
            credential_id=bytes(row["credential_id"]),
            public_key=bytes(row["public_key"]),
            sign_count=int(row["sign_count"]),
            transports=transports,
            created_at=float(row["created_at"]),
            last_seen_at=float(row["last_seen_at"]),
        )

    def revoke_device(self, device_id: str) -> bool:
        self._require_enabled()
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE remote_devices SET revoked = 1 WHERE device_id = ? AND revoked = 0",
                (device_id,),
            )
            changed = cursor.rowcount == 1
            remaining = connection.execute(
                "SELECT COUNT(*) AS count FROM remote_devices WHERE revoked = 0"
            ).fetchone()["count"]
            if remaining == 0 and not self.settings.remote_allowed_login:
                connection.execute("DELETE FROM remote_metadata WHERE key = 'owner_login'")
        for token_hash, session in tuple(self._sessions.items()):
            if session.device_id == device_id:
                self._sessions.pop(token_hash, None)
        if changed:
            self.record_event(device_id, "device", "revoked", "Dispositivo revocado")
        return changed

    def record_event(self, device_id: str | None, kind: str, status: str, summary: str) -> None:
        if not self.enabled:
            return
        clean_kind = kind.strip()[:40] or "event"
        clean_status = status.strip()[:40] or "unknown"
        clean_summary = " ".join(summary.split()).strip()[:240]
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO remote_activity(device_id, kind, status, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (device_id, clean_kind, clean_status, clean_summary, time.time()),
            )
            connection.execute(
                """
                DELETE FROM remote_activity
                WHERE activity_id NOT IN (
                    SELECT activity_id FROM remote_activity
                    ORDER BY activity_id DESC LIMIT 500
                )
                """
            )

    def recent_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        safe_limit = max(1, min(limit, 100))
        with self._lock, closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT activity_id, device_id, kind, status, summary, created_at
                FROM remote_activity
                ORDER BY activity_id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]
