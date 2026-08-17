from __future__ import annotations

import builtins
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jarvis.capabilities.files import AttachmentError, AttachmentStore


def test_attachment_name_is_data_and_content_stays_in_the_injected_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    store = AttachmentStore(root)

    attachment = store.save_bytes(
        "owner",
        r"..\..\outside\private.txt",
        "text/plain",
        b"contenido local",
    )
    content = store.content_path("owner", attachment.attachment_id)

    assert attachment.original_name == "private.txt"
    assert content.parent == root.resolve()
    assert content.name.startswith(attachment.attachment_id)
    assert not (tmp_path.parent / "outside" / "private.txt").exists()
    assert store.read_text("owner", attachment.attachment_id) == "contenido local"


@pytest.mark.parametrize(
    ("filename", "media_type", "data"),
    [
        ("imagen.png", "image/png", b"esto no es una imagen"),
        ("documento.pdf", "application/pdf", b"esto no es un pdf"),
    ],
)
def test_attachment_rejects_spoofed_mime_even_when_extension_and_header_agree(
    tmp_path: Path,
    filename: str,
    media_type: str,
    data: bytes,
) -> None:
    store = AttachmentStore(tmp_path / "vault")

    with pytest.raises(AttachmentError, match="coincide|permitido"):
        store.save_bytes("owner", filename, media_type, data)


def test_attachment_oversize_is_rejected_without_leaving_partial_files(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    store = AttachmentStore(root, max_bytes=1_024)

    with pytest.raises(AttachmentError, match="límite"):
        store.save_bytes("owner", "large.txt", "text/plain", b"x" * 1_025)

    assert not root.exists() or tuple(root.iterdir()) == ()


def test_attachment_access_list_and_delete_are_session_isolated(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "vault")
    attachment = store.save_bytes("owner", "notes.txt", "text/plain", b"private")

    assert len(store.list("owner")) == 1
    assert store.list("other") == []
    with pytest.raises(AttachmentError, match="sesión"):
        store.get("other", attachment.attachment_id)
    with pytest.raises(AttachmentError, match="sesión"):
        store.delete("other", attachment.attachment_id)
    assert store.delete("owner", attachment.attachment_id) is True
    assert store.list("owner") == []


def test_cleanup_removes_expired_ephemeral_files_but_keeps_persistent_ones(
    tmp_path: Path,
) -> None:
    store = AttachmentStore(tmp_path / "vault", retention_hours=1)
    ephemeral = store.save_bytes("owner", "temporary.txt", "text/plain", b"temporary")
    persistent = store.save_bytes(
        "owner",
        "indexed.txt",
        "text/plain",
        b"persistent",
        persistent=True,
    )
    future = datetime.fromisoformat(ephemeral.expires_at) + timedelta(seconds=1)

    removed = store.cleanup(future)

    assert removed == 1
    with pytest.raises(AttachmentError):
        store.get("owner", ephemeral.attachment_id)
    assert store.get("owner", persistent.attachment_id).persistent is True


def test_pdf_without_optional_dependency_fails_honestly_and_keeps_the_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AttachmentStore(tmp_path / "vault")
    attachment = store.save_bytes(
        "owner",
        "document.pdf",
        "application/pdf",
        b"%PDF-1.4\n%%EOF\n",
    )
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name == "pypdf":
            raise ImportError("simulated optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(AttachmentError, match="pypdf"):
        store.read_text("owner", attachment.attachment_id)

    assert store.content_path("owner", attachment.attachment_id).is_file()
