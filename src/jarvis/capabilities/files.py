from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import stat
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

_SAFE_TEXT_MIME = frozenset(
    {
        "application/csv",
        "application/json",
        "application/pdf",
        "application/xml",
        "text/csv",
        "text/markdown",
        "text/plain",
        "text/xml",
    }
)
_SAFE_IMAGE_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_SAFE_EXTENSIONS = frozenset(
    {".csv", ".json", ".md", ".pdf", ".txt", ".xml", ".jpg", ".jpeg", ".png", ".webp"}
)
_OPAQUE_ID = re.compile(r"^[a-f0-9]{32}$")
_SESSION_HASH = re.compile(r"^[a-f0-9]{24}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class AttachmentError(ValueError):
    """A bounded, user-facing attachment validation error."""


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: str
    session_hash: str
    original_name: str
    media_type: str
    size: int
    sha256: str
    created_at: str
    expires_at: str
    persistent: bool = False

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("session_hash", None)
        payload["id"] = self.attachment_id
        return payload


class AttachmentStore:
    """Private upload vault.

    Files are always renamed to opaque IDs, never served as static content, and may only
    be resolved with the session that created them. The store never follows a user path.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = 12 * 1024 * 1024,
        max_session_bytes: int = 256 * 1024 * 1024,
        retention_hours: int = 24,
    ) -> None:
        unresolved_root = Path(root).absolute()
        self._assert_safe_root_chain(unresolved_root)
        self._declared_root = unresolved_root
        self.root = unresolved_root.resolve()
        self.max_bytes = max(1_024, max_bytes)
        self.max_session_bytes = max(self.max_bytes, max_session_bytes)
        self.retention_hours = max(1, min(retention_hours, 24 * 30))
        self._lock = threading.RLock()

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return path.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        except OSError:
            return False

    @classmethod
    def _assert_safe_root_chain(cls, root: Path) -> None:
        for candidate in (root, *root.parents):
            if cls._is_link_or_reparse(candidate):
                raise AttachmentError(
                    "La b\u00f3veda de adjuntos no puede atravesar enlaces o reparse points."
                )

    def _ensure_root(self) -> None:
        self._assert_safe_root_chain(self._declared_root)
        self._declared_root.mkdir(parents=True, exist_ok=True)
        self._assert_safe_root_chain(self._declared_root)
        try:
            resolved = self._declared_root.resolve(strict=True)
        except OSError as exc:
            raise AttachmentError("La b\u00f3veda privada de adjuntos no es segura.") from exc
        if resolved != self.root or not resolved.is_dir():
            raise AttachmentError("La b\u00f3veda privada de adjuntos no es segura.")

    @staticmethod
    def _session_hash(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _safe_name(filename: str | None) -> str:
        raw = (filename or "archivo").replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = re.sub(r"[^\w .()\-]+", "_", raw, flags=re.UNICODE).strip(" .")
        return (cleaned or "archivo")[:120]

    @staticmethod
    def _sniff(data: bytes, declared: str, suffix: str) -> str:
        declared = declared.split(";", 1)[0].strip().casefold()
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            detected = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            detected = "image/jpeg"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            detected = "image/webp"
        elif data.startswith(b"%PDF-"):
            detected = "application/pdf"
        else:
            if suffix in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
                raise AttachmentError(
                    "El contenido del archivo no coincide con su extensi\u00f3n declarada."
                )
            detected = mimetypes.types_map.get(suffix, declared or "application/octet-stream")
            if suffix in {".txt", ".md", ".csv", ".json", ".xml"}:
                try:
                    data[:8_192].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise AttachmentError("El archivo de texto no usa UTF-8 v\u00e1lido.") from exc
        allowed = _SAFE_TEXT_MIME | _SAFE_IMAGE_MIME
        if suffix not in _SAFE_EXTENSIONS or detected not in allowed:
            raise AttachmentError("Ese tipo de archivo no est\u00e1 permitido.")
        if declared and declared not in allowed and declared != "application/octet-stream":
            raise AttachmentError("El tipo declarado del archivo no es seguro.")
        if declared in _SAFE_IMAGE_MIME and detected != declared:
            raise AttachmentError("El contenido de la imagen no coincide con su tipo declarado.")
        return detected

    def _metadata_path(self, attachment_id: str) -> Path:
        return self.root / f"{attachment_id}.metadata.json"

    def _legacy_metadata_path(self, attachment_id: str) -> Path:
        return self.root / f"{attachment_id}.json"

    def _content_path(self, attachment_id: str, suffix: str) -> Path:
        return self.root / f"{attachment_id}{suffix}"

    def _validate_id(self, attachment_id: str) -> str:
        if not _OPAQUE_ID.fullmatch(attachment_id):
            raise AttachmentError("Identificador de adjunto inv\u00e1lido.")
        return attachment_id

    def save_bytes(
        self,
        session_id: str,
        filename: str | None,
        media_type: str,
        data: bytes,
        *,
        persistent: bool = False,
    ) -> Attachment:
        if not data:
            raise AttachmentError("El archivo est\u00e1 vac\u00edo.")
        if len(data) > self.max_bytes:
            raise AttachmentError("El archivo supera el l\u00edmite permitido.")
        safe_name = self._safe_name(filename)
        suffix = Path(safe_name).suffix.casefold()
        detected = self._sniff(data, media_type, suffix)
        now = datetime.now(UTC)
        expires = now + timedelta(hours=self.retention_hours)
        attachment = Attachment(
            attachment_id=uuid4().hex,
            session_hash=self._session_hash(session_id),
            original_name=safe_name,
            media_type=detected,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
            persistent=bool(persistent),
        )
        content_path = self._content_path(attachment.attachment_id, suffix)
        metadata_path = self._metadata_path(attachment.attachment_id)
        with self._lock:
            self._ensure_root()
            self.cleanup()
            current_size = sum(
                int(item.get("size", 0))
                for item in self.list(session_id)
                if isinstance(item.get("size"), int)
            )
            if current_size + len(data) > self.max_session_bytes:
                raise AttachmentError("La sesi\u00f3n alcanz\u00f3 su cuota privada de adjuntos.")
            try:
                with content_path.open("xb") as content_file:
                    content_file.write(data)
                with metadata_path.open("x", encoding="utf-8", newline="\n") as metadata_file:
                    json.dump(
                        asdict(attachment),
                        metadata_file,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
            except Exception:
                content_path.unlink(missing_ok=True)
                metadata_path.unlink(missing_ok=True)
                raise
        return attachment

    def save_stream(
        self,
        session_id: str,
        filename: str | None,
        media_type: str,
        stream: BinaryIO,
    ) -> Attachment:
        data = stream.read(self.max_bytes + 1)
        return self.save_bytes(session_id, filename, media_type, data)

    def _load(self, attachment_id: str) -> Attachment:
        attachment_id = self._validate_id(attachment_id)
        self._assert_safe_root_chain(self._declared_root)
        metadata_path = self._metadata_path(attachment_id)
        if not metadata_path.exists():
            metadata_path = self._legacy_metadata_path(attachment_id)
        try:
            if (
                self._is_link_or_reparse(metadata_path)
                or metadata_path.resolve(strict=True).parent != self.root
                or metadata_path.stat().st_size > 16_384
            ):
                raise AttachmentError("Los metadatos del adjunto no son seguros.")
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            attachment = Attachment(**payload)
            created_at = datetime.fromisoformat(attachment.created_at)
            expires_at = datetime.fromisoformat(attachment.expires_at)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AttachmentError("El adjunto no existe o ya expir\u00f3.") from exc
        if (
            not all(
                isinstance(value, str)
                for value in (
                    attachment.attachment_id,
                    attachment.session_hash,
                    attachment.original_name,
                    attachment.media_type,
                    attachment.sha256,
                    attachment.created_at,
                    attachment.expires_at,
                )
            )
            or attachment.attachment_id != attachment_id
            or _SESSION_HASH.fullmatch(attachment.session_hash) is None
            or self._safe_name(attachment.original_name) != attachment.original_name
            or attachment.media_type not in (_SAFE_TEXT_MIME | _SAFE_IMAGE_MIME)
            or not isinstance(attachment.size, int)
            or isinstance(attachment.size, bool)
            or not 0 < attachment.size <= self.max_bytes
            or _SHA256.fullmatch(attachment.sha256) is None
            or not isinstance(attachment.persistent, bool)
            or created_at.tzinfo is None
            or expires_at.tzinfo is None
        ):
            raise AttachmentError("Los metadatos del adjunto no son v\u00e1lidos.")
        if not attachment.persistent and expires_at <= datetime.now(UTC):
            raise AttachmentError("El adjunto no existe o ya expir\u00f3.")
        return attachment

    def get(self, session_id: str, attachment_id: str) -> Attachment:
        attachment = self._load(attachment_id)
        if attachment.session_hash != self._session_hash(session_id):
            raise AttachmentError("El adjunto no pertenece a esta sesi\u00f3n.")
        return attachment

    def content_path(self, session_id: str, attachment_id: str) -> Path:
        attachment = self.get(session_id, attachment_id)
        metadata_path = self._metadata_path(attachment.attachment_id)
        if not metadata_path.exists():
            metadata_path = self._legacy_metadata_path(attachment.attachment_id)
        matches = [
            path
            for path in self.root.glob(f"{attachment.attachment_id}.*")
            if path != metadata_path
        ]
        if len(matches) != 1:
            raise AttachmentError("No pude resolver el contenido del adjunto de forma segura.")
        content_path = matches[0]
        try:
            if (
                self._is_link_or_reparse(content_path)
                or content_path.resolve(strict=True).parent != self.root
                or not content_path.is_file()
                or content_path.stat().st_size != attachment.size
            ):
                raise AttachmentError("El contenido del adjunto cambi\u00f3 o no es seguro.")
            digest = hashlib.sha256(content_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise AttachmentError("No pude leer el contenido privado del adjunto.") from exc
        if digest != attachment.sha256:
            raise AttachmentError("El contenido del adjunto cambi\u00f3 o no es seguro.")
        return content_path

    def read_text(self, session_id: str, attachment_id: str, maximum: int = 120_000) -> str:
        attachment = self.get(session_id, attachment_id)
        if attachment.media_type == "application/pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise AttachmentError(
                    "La extracci\u00f3n de PDF requiere el complemento opcional pypdf."
                ) from exc
            try:
                reader = PdfReader(self.content_path(session_id, attachment_id))
                if reader.is_encrypted:
                    raise AttachmentError("No puedo leer un PDF cifrado.")
                parts: list[str] = []
                size = 0
                for index, page in enumerate(reader.pages):
                    if index >= 200:
                        break
                    text = page.extract_text() or ""
                    remaining = maximum - size
                    if remaining <= 0:
                        break
                    parts.append(text[:remaining])
                    size += len(parts[-1])
                return "\n".join(parts).strip()
            except AttachmentError:
                raise
            except Exception as exc:
                raise AttachmentError("No pude extraer texto seguro del PDF.") from exc
        if attachment.media_type not in _SAFE_TEXT_MIME:
            raise AttachmentError("Ese adjunto no contiene texto legible.")
        return self.content_path(session_id, attachment_id).read_text(encoding="utf-8")[:maximum]

    def list(self, session_id: str) -> list[dict[str, object]]:
        session_hash = self._session_hash(session_id)
        entries: list[Attachment] = []
        self._assert_safe_root_chain(self._declared_root)
        if not self.root.exists():
            return []
        with self._lock:
            identifiers = {
                path.name.removesuffix(".metadata.json")
                for path in self.root.glob("*.metadata.json")
            }
            identifiers.update(
                path.stem
                for path in self.root.glob("*.json")
                if _OPAQUE_ID.fullmatch(path.stem)
                and not self._metadata_path(path.stem).exists()
                and any(sibling != path for sibling in self.root.glob(f"{path.stem}.*"))
            )
            for attachment_id in identifiers:
                try:
                    item = self._load(attachment_id)
                except AttachmentError:
                    continue
                if item.session_hash == session_hash:
                    entries.append(item)
        entries.sort(key=lambda item: item.created_at, reverse=True)
        return [item.public_dict() for item in entries]

    def delete(self, session_id: str, attachment_id: str) -> bool:
        attachment = self.get(session_id, attachment_id)
        with self._lock:
            paths = [
                self._metadata_path(attachment.attachment_id),
                self._legacy_metadata_path(attachment.attachment_id),
            ]
            paths.extend(self.root.glob(f"{attachment.attachment_id}.*"))
            removed = False
            for path in set(paths):
                if path.parent.resolve() == self.root and path.exists():
                    path.unlink()
                    removed = True
            return removed

    def cleanup(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
        with self._lock:
            removed = 0
            self._assert_safe_root_chain(self._declared_root)
            if not self.root.exists():
                return 0
            identifiers = {
                path.name.removesuffix(".metadata.json")
                for path in self.root.glob("*.metadata.json")
            }
            identifiers.update(
                path.stem
                for path in self.root.glob("*.json")
                if _OPAQUE_ID.fullmatch(path.stem)
                and not self._metadata_path(path.stem).exists()
                and any(sibling != path for sibling in self.root.glob(f"{path.stem}.*"))
            )
            for identifier in identifiers:
                if not _OPAQUE_ID.fullmatch(identifier):
                    continue
                metadata_path = self._metadata_path(identifier)
                if not metadata_path.exists():
                    metadata_path = self._legacy_metadata_path(identifier)
                try:
                    if (
                        self._is_link_or_reparse(metadata_path)
                        or metadata_path.resolve(strict=True).parent != self.root
                        or metadata_path.stat().st_size > 16_384
                    ):
                        raise ValueError("unsafe metadata")
                    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                    item = Attachment(**payload)
                    expired = datetime.fromisoformat(item.expires_at) <= current
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    expired = True
                    item = None
                if not expired or (item is not None and item.persistent is True):
                    continue
                for path in self.root.glob(f"{identifier}.*"):
                    if path.parent.resolve() == self.root:
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            continue
                removed += 1
            return removed
