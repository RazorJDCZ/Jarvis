from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from jarvis.capabilities.connectors import AppaConnector, ConnectorError
from jarvis.capabilities.developer import DeveloperWorkspace, WorkspaceSecurityError
from jarvis.capabilities.files import AttachmentError, AttachmentStore


def test_json_attachment_content_never_collides_with_private_metadata(
    tmp_path: Path,
) -> None:
    store = AttachmentStore(tmp_path / "vault")
    content = b'{"project":"Jarvis","private":true}'

    attachment = store.save_bytes(
        "owner",
        "context.json",
        "application/json",
        content,
    )

    assert store.content_path("owner", attachment.attachment_id).read_bytes() == content
    assert store.read_text("owner", attachment.attachment_id) == content.decode()
    assert len(store.list("owner")) == 1


def test_expired_attachment_is_denied_without_waiting_for_cleanup(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "vault")
    attachment = store.save_bytes("owner", "notes.txt", "text/plain", b"private")
    metadata_path = store._metadata_path(attachment.attachment_id)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AttachmentError, match="expir"):
        store.get("owner", attachment.attachment_id)
    assert store.list("owner") == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attachment_id", "0" * 32),
        ("session_hash", 42),
        ("size", True),
        ("sha256", "not-a-digest"),
        ("expires_at", "2026-08-10T00:00:00"),
    ],
)
def test_tampered_attachment_metadata_fails_closed(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    store = AttachmentStore(tmp_path / field)
    attachment = store.save_bytes("owner", "notes.txt", "text/plain", b"private")
    metadata_path = store._metadata_path(attachment.attachment_id)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload[field] = value
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AttachmentError):
        store.get("owner", attachment.attachment_id)


def test_attachment_content_hash_is_verified_before_use(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "vault")
    attachment = store.save_bytes("owner", "notes.txt", "text/plain", b"private")
    content_path = store.content_path("owner", attachment.attachment_id)
    content_path.write_bytes(b"changed")

    with pytest.raises(AttachmentError, match="cambi"):
        store.content_path("owner", attachment.attachment_id)


def test_saving_cleans_expired_files_during_a_long_running_session(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "vault")
    expired = store.save_bytes("owner", "old.txt", "text/plain", b"old")
    metadata_path = store._metadata_path(expired.attachment_id)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    store.save_bytes("owner", "new.txt", "text/plain", b"new")

    assert tuple(store.root.glob(f"{expired.attachment_id}.*")) == ()


def test_solitary_json_content_is_not_mistaken_for_legacy_metadata(tmp_path: Path) -> None:
    store = AttachmentStore(tmp_path / "vault")
    store.root.mkdir()
    orphan = store.root / f"{'a' * 32}.json"
    orphan.write_text('{"arbitrary":"user content"}', encoding="utf-8")

    assert store.list("owner") == []
    assert store.cleanup(datetime.now(UTC) + timedelta(days=365)) == 0
    assert orphan.is_file()


def test_attachment_root_rejects_a_linked_ancestor(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create directory symlinks")

    with pytest.raises(AttachmentError, match="enlaces|reparse"):
        AttachmentStore(linked_parent / "missing-vault")


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@appa.example",
        "https://appa.example/api?redirect=elsewhere",
        "https://appa.example/api#fragment",
        "https://appa.example/api/../admin",
        "https://appa.example:invalid",
    ],
)
def test_appa_rejects_ambiguous_or_credential_bearing_base_urls(base_url: str) -> None:
    with pytest.raises(ConnectorError):
        AppaConnector(base_url, "token")


@pytest.mark.asyncio
async def test_appa_rejects_task_path_injection_before_creating_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_client(**_kwargs: object):
        raise AssertionError("No HTTP client should be created for an invalid task ID")

    monkeypatch.setattr(
        "jarvis.capabilities.connectors.httpx.AsyncClient",
        forbidden_client,
    )
    connector = AppaConnector("https://appa.example", "token")

    with pytest.raises(ConnectorError, match="identificador"):
        await connector.complete_task("owner", "../admin")


@pytest.mark.asyncio
async def test_appa_rejects_malicious_task_ids_returned_by_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "appa-jarvis-bridge",
                "api_version": "v1",
                "capabilities": ["tasks.read", "tasks.write"],
            }
            if request.url.path.endswith("/health")
            else {"tasks": [{"id": "../admin", "title": "Injected"}]},
        )
    )
    original_client = httpx.AsyncClient

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(
        "jarvis.capabilities.connectors.httpx.AsyncClient",
        client_factory,
    )

    connector = AppaConnector("https://appa.example", "token")
    with pytest.raises(ConnectorError, match="incompleta"):
        await connector.list_tasks("owner")
    await connector.close()


@pytest.mark.parametrize("anchored", [r"\Windows\win.ini", r"C:Windows\win.ini"])
def test_developer_workspace_rejects_windows_anchored_paths_early(
    tmp_path: Path,
    anchored: str,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = DeveloperWorkspace({"project": root})

    with pytest.raises(WorkspaceSecurityError, match="debe ser relativa"):
        workspace.read("project", anchored)
