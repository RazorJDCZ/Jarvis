from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from jarvis.config import Settings
from jarvis.main import create_app
from jarvis.services.mail import MailService
from jarvis.services.mail_providers import MailError
from jarvis.services.notifications import NotificationStore
from jarvis.services.organizer import (
    APPA_DESKTOP_SESSION,
    TZ,
    CalendarEventEdit,
    EventReview,
    Organizer,
    StudyRequest,
    date_suggestion,
)
from jarvis.services.recovery import Recovery
from jarvis.services.web_push import WebPush


@pytest.fixture
def organizer(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.services.mail_store.protect", lambda b, decrypt=False: b)
    settings = Settings(
        project_root=tmp_path,
        brain_mode="fallback",
        voice_preload=False,
        adaptive_resources=False,
        semantic_enabled=False,
        appa_auto_discover=False,
        action_model_planning=False,
    )
    mail = MailService(settings, None)
    service = Organizer(settings, mail, None)
    service.calendar.store.connect(
        "google",
        "fixture@example.com",
        {
            "access_token": "fixture",
            "refresh_token": "fixture",
            "expires_at": time.time() + 3600,
            "client": {"client_id": "fixture.apps.googleusercontent.com"},
        },
    )
    service.calendar.managed_calendar = AsyncMock(return_value="fixture-calendar")
    service.recovery = Recovery(settings)
    return service


def mail_proposal(service):
    account = service.mail.store.connect("microsoft", "student@example.com", {})
    service.mail.store.ingest(
        account,
        {
            "thread_id": "thread",
            "version": "v1",
            "subject": "Entrega de informe",
            "sender": "Docente",
            "received": "2026-09-20T12:00:00Z",
            "body": "Entregar el 28 de septiembre de 2026 a las 15:00.",
            "url": "https://outlook.office.com/mail/",
        },
    )
    item = service.mail.store.list()[0]
    service.mail.store.update(item["id"], deadline="28 de septiembre de 2026 a las 15:00")
    return service.proposals()[0]


def review(proposal):
    return EventReview(**{k: proposal[k] for k in EventReview.model_fields})


def subscription():
    public = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/synthetic",
        "keys": {
            "auth": base64.urlsafe_b64encode(b"0" * 16).decode(),
            "p256dh": base64.urlsafe_b64encode(public).decode(),
        },
    }


@pytest.mark.parametrize(
    "text",
    ["el viernes", "mañana a las 14:00", "03/04/2026", "28 de septiembre", "31 de febrero de 2026"],
)
def test_ambiguous_dates_need_review(text):
    assert date_suggestion(text, "2026-09-20")[0] == ""


def test_explicit_dates_timezone_and_all_day():
    start, end, all_day, _ = date_suggestion("28 de septiembre de 2026 a las 15:30", "")
    assert start == "2026-09-28T15:30:00-05:00" and end.endswith("16:30:00-05:00")
    assert not all_day
    assert date_suggestion("2026-12-31", "")[:3] == ("2026-12-31", "2027-01-01", True)


def test_proposals_persist_and_new_message_invalidates_review(organizer):
    proposal = mail_proposal(organizer)
    assert organizer.proposals()[0]["revision"] == proposal["revision"]
    organizer.store.put(
        "proposal",
        proposal["id"],
        {**proposal, "state": "published", "published": {"id": "original"}},
    )
    item = organizer.mail.store.get(proposal["mail_id"])
    organizer.mail.store.ingest(
        item["account_id"], {**item, "version": "v2", "received": "2026-09-21T12:00:00Z"}
    )
    organizer.mail.store.update(item["id"], deadline="2026-09-30")
    updated = organizer.proposals()[0]
    assert updated["source_key"] == proposal["source_key"]
    assert updated["revision"] != proposal["revision"] and updated["published"]["id"] == "original"


@pytest.mark.asyncio
async def test_calendar_lost_create_response_and_duplicate_click(organizer):
    proposal = mail_proposal(organizer)
    saved, inserts = {}, []

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            inserts.append(payload["id"])
            if saved:
                return httpx.Response(409)
            saved.update(payload, etag="etag1", htmlLink="https://calendar.google.com/")
            raise httpx.ReadTimeout("lost response")
        return httpx.Response(200, json=saved)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        organizer.calendar.client = client
        with pytest.raises(httpx.ReadTimeout):
            await organizer.publish(proposal["id"], review(proposal))
        result = await organizer.publish(proposal["id"], review(proposal))
        assert inserts[0] == inserts[1] == result["id"]
        await organizer.publish(proposal["id"], review(proposal))
        assert len(inserts) == 2


@pytest.mark.asyncio
async def test_external_calendar_edit_is_not_overwritten(organizer):
    proposal = mail_proposal(organizer)
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={**json.loads(request.content), "etag": "old"})
        if request.method == "PATCH":
            assert request.headers["if-match"] == "old"
            return httpx.Response(412)
        return httpx.Response(200, json={"summary": "Manual edit", "etag": "new"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        organizer.calendar.client = client
        await organizer.publish(proposal["id"], review(proposal))
        changed = review(proposal).model_copy(update={"title": "New title"})
        with pytest.raises(MailError, match="cambió"):
            await organizer.publish(proposal["id"], changed)
        assert [r.method for r in requests] == ["POST", "PATCH", "GET"]


@pytest.mark.asyncio
async def test_sync_is_atomic_paginated_and_removes_deleted_events(organizer):
    organizer.store.put("google_event", "stale", {"id": "stale"})
    organizer.calendar.calendars = AsyncMock(return_value=[{"id": "one", "accessRole": "reader"}])

    def handler(request):
        if "pageToken" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "one",
                            "summary": "Clase",
                            "start": {"date": "2026-10-01"},
                            "end": {"date": "2026-10-02"},
                        }
                    ],
                    "nextPageToken": "page2",
                },
            )
        return httpx.Response(200, json={"items": [{"id": "cancelled", "status": "cancelled"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        organizer.calendar.client = client
        await organizer.calendar.sync()
    assert [e["id"] for e in organizer.store.list("google_event")] == ["one:one"]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    ) as client:
        organizer.calendar.client = client
        await organizer.calendar.sync()
    assert organizer.calendar.status()["error"]
    assert organizer.store.list("google_event")[0]["title"] == "Clase"


@pytest.mark.asyncio
async def test_sync_marks_only_jarvis_owned_calendar_events_editable(organizer):
    account_id = organizer.calendar.store.accounts()[0]["id"]
    organizer.store.put("meta", "calendar:" + account_id, "fixture-calendar")
    organizer.calendar.calendars = AsyncMock(
        return_value=[
            {
                "id": "fixture-calendar",
                "summary": "Jarvis",
                "accessRole": "owner",
                "description": "Jarvis Local Core · calendario administrado",
            },
            {"id": "shared", "summary": "Universidad", "accessRole": "writer"},
        ]
    )

    def handler(request):
        calendar_id = request.url.path.split("/calendars/", 1)[1].split("/events", 1)[0]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "event-" + calendar_id,
                        "summary": "Clase",
                        "etag": '"v1"',
                        "start": {"dateTime": "2026-10-20T10:00:00-05:00"},
                        "end": {"dateTime": "2026-10-20T11:00:00-05:00"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        organizer.calendar.client = client
        await organizer.calendar.sync()

    events = {event["calendar_id"]: event for event in organizer.store.list("google_event")}
    assert events["fixture-calendar"]["editable"] is True
    assert events["shared"]["editable"] is False


@pytest.mark.asyncio
async def test_appa_calendar_edit_uses_etag_and_updates_cached_event(organizer):
    cached = {
        "id": "fixture-calendar:event-1",
        "calendar_id": "fixture-calendar",
        "event_id": "event-1",
        "title": "Clase",
        "description": "Original",
        "start_at": "2026-10-20T10:00:00-05:00",
        "end_at": "2026-10-20T11:00:00-05:00",
        "all_day": False,
        "busy": True,
        "source": "Google Calendar",
        "url": "https://calendar.google.com/event",
        "calendar": "Jarvis",
        "etag": '"old"',
        "reminders": [60],
        "editable": True,
    }
    organizer.store.put("google_event", cached["id"], cached)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "PATCH"
        assert request.headers["if-match"] == '"old"'
        payload = json.loads(request.content)
        assert payload["summary"] == "Clase movida"
        assert payload["reminders"]["overrides"] == [{"method": "popup", "minutes": 30}]
        return httpx.Response(
            200,
            json={**payload, "id": "event-1", "etag": '"new"', "htmlLink": cached["url"]},
        )

    edit = CalendarEventEdit(
        event_id=cached["id"],
        etag='"old"',
        title="Clase movida",
        description="Actualizada",
        start_at="2026-10-20T12:00:00-05:00",
        end_at="2026-10-20T13:00:00-05:00",
        reminders=[30],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        organizer.calendar.client = client
        updated = await organizer.edit_google_event(edit)

    assert len(requests) == 1
    assert updated["title"] == "Clase movida" and updated["etag"] == '"new"'
    assert organizer.store.get("google_event", cached["id"])["start_at"].endswith("12:00:00-05:00")
    with pytest.raises(MailError, match="cambió"):
        await organizer.edit_google_event(edit)


@pytest.mark.asyncio
async def test_calendar_oauth_separate_from_mail(organizer):
    organizer.mail.configure("google", "fixture.apps.googleusercontent.com", "fixture")
    url = await organizer.calendar.begin_auth()
    params = parse_qs(urlsplit(url).query)
    assert (
        "calendar.app.created" in params["scope"][0] and "gmail.readonly" not in params["scope"][0]
    )
    assert params["code_challenge_method"] == ["S256"]
    assert organizer.calendar.store.path != organizer.mail.store.path
    await organizer.calendar.close()


def test_capture_idempotency_device_isolation_and_restart(organizer):
    first = organizer.capture("Una idea", "remote:device1:chat", "a" * 32)
    assert organizer.capture("Changed", "remote:device1:other", "a" * 32) == first
    assert not organizer.today("remote:device2:other")["captures"]
    assert organizer.today()["captures"][0]["text"] == "Una idea"
    fresh = Organizer(organizer.config, organizer.mail, None)
    assert fresh.today("remote:device1:tab")["captures"][0]["id"] == first["id"]


def test_study_spreads_sessions_respects_busy_and_reports_shortfall(organizer):
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    organizer.store.put(
        "google_event",
        "busy",
        {
            "id": "busy",
            "start_at": tomorrow.isoformat() + "T16:00:00-05:00",
            "end_at": tomorrow.isoformat() + "T17:00:00-05:00",
            "busy": True,
        },
    )
    result = organizer.study(
        StudyRequest(
            title="Cálculo",
            deadline=tomorrow + timedelta(days=2),
            sessions=5,
            minutes=45,
            weekdays=list(range(7)),
        )
    )
    assert result["missing"] == 5 - len(result["slots"])
    starts = [s["start_at"] for s in result["slots"]]
    assert len({s[:10] for s in starts}) == len(starts)
    assert not any(s.startswith(tomorrow.isoformat() + "T16:") for s in starts)
    assert all(s["state"] == "review" for s in result["slots"])


def test_today_ignores_completed_tasks_and_orders_deadlines(organizer):
    organizer.store.put(
        "meta",
        "appa",
        {
            "tasks": [
                {"id": "done", "title": "Done", "completed": True},
                {"id": "later", "title": "Later", "due": "2026-12-01"},
                {"id": "early", "title": "Early", "due": "2026-10-01"},
            ],
            "events": [],
        },
    )
    assert [t["id"] for t in organizer.today()["tasks"]] == ["early", "later"]


@pytest.mark.asyncio
async def test_push_delivery_retry_dedup_revocation_and_privacy(organizer, tmp_path):
    outbox = NotificationStore(tmp_path / "notifications.sqlite3")
    organizer.capabilities = SimpleNamespace(
        outbox=outbox, preferences=SimpleNamespace(quiet=lambda h: False)
    )
    remote = SimpleNamespace(get_device=Mock(return_value=True))
    push = WebPush(organizer, remote)
    registered = push.subscribe(subscription(), "remote:device1:inbox", "device1")
    outbox.publish(
        "remote:device1:inbox",
        {
            "event": "reminder",
            "id": "r",
            "title": "PRIVATE EMAIL",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    push.send = Mock(side_effect=RuntimeError("offline"))
    await push.deliver()
    assert push.send.call_count == 1
    await push.deliver()
    assert push.send.call_count == 1
    organizer.store.replace("push_delivery", {})
    push.send = Mock()
    await push.deliver()
    await push.deliver()
    assert push.send.call_count == 1 and "PRIVATE EMAIL" not in str(push.send.call_args)
    remote.get_device.return_value = None
    await push.deliver()
    assert not organizer.store.get("subscription", registered["id"])


@pytest.mark.asyncio
async def test_appa_native_notifications_retry_and_acknowledge(organizer, tmp_path):
    outbox = NotificationStore(tmp_path / "appa-notifications.sqlite3")
    outbox.register(APPA_DESKTOP_SESSION)
    item = outbox.publish(
        APPA_DESKTOP_SESSION,
        {
            "event": "briefing",
            "id": "class:2026-10-13T15:00:00-05:00",
            "title": "PRIVATE EMAIL\n" + "contenido " * 100,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    connector = SimpleNamespace(send_notification=AsyncMock(side_effect=RuntimeError("offline")))
    organizer.capabilities = SimpleNamespace(
        outbox=outbox,
        preferences=SimpleNamespace(quiet=lambda hour: False),
        connectors=SimpleNamespace(require_appa=lambda: connector),
    )
    push = WebPush(organizer, SimpleNamespace(get_device=lambda device: True))

    await push.deliver()
    assert outbox.pending(APPA_DESKTOP_SESSION)
    connector.send_notification = AsyncMock()
    await push.deliver()

    connector.send_notification.assert_awaited_once_with(
        "Jarvis", "Tu resumen diario está listo para revisar.", item["notification_id"]
    )
    assert not outbox.pending(APPA_DESKTOP_SESSION)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/a",
        "https://127.0.0.1/",
        "https://fcm.googleapis.com.evil.test/a",
        "https://fcm.googleapis.com:123/a",
        "https://user@fcm.googleapis.com/a",
    ],
)
def test_push_rejects_arbitrary_destinations(organizer, endpoint):
    with pytest.raises(MailError):
        WebPush(organizer, None).subscribe({**subscription(), "endpoint": endpoint}, "local:inbox")


@pytest.mark.asyncio
async def test_followups_obey_state_age_snooze_quiet_hours(organizer, tmp_path):
    proposal = mail_proposal(organizer)
    outbox = NotificationStore(tmp_path / "notifications.sqlite3")
    outbox.register("local:inbox")
    notify = AsyncMock()
    preferences = SimpleNamespace(quiet=Mock(return_value=False))
    organizer.capabilities = SimpleNamespace(outbox=outbox, preferences=preferences, _notify=notify)
    organizer.mail.store.update(proposal["mail_id"], state="waiting")
    await organizer.followups()
    assert not notify.called
    organizer.store.put(
        "mail_state",
        proposal["mail_id"],
        {"state": "waiting", "version": "v1", "since": time.time() - 4 * 86400},
    )
    await organizer.followups()
    await organizer.followups()
    assert notify.call_count == 1
    organizer.store.replace("throttle", {})
    preferences.quiet.return_value = True
    await organizer.followups()
    assert notify.call_count == 1
    preferences.quiet.return_value = False
    organizer.mail.store.update(proposal["mail_id"], snoozed_until=time.time() + 100)
    await organizer.followups()
    assert notify.call_count == 1


def test_encrypted_backup_roundtrip_and_path_rejection(organizer):
    organizer.capture("Before", "default", "b" * 32)
    result = organizer.recovery.backup()
    archive = organizer.recovery.folder / result["name"]
    assert not archive.read_bytes().startswith(b"PK")
    organizer.store.replace("capture", {})
    organizer.recovery.restore(result["name"])
    assert organizer.today()["captures"][0]["text"] == "Before"
    with pytest.raises(ValueError):
        organizer.recovery.restore("../../outside.jbackup")


def test_real_webpush_encrypts_and_signs_without_external_network(organizer, monkeypatch):
    import requests

    captured = []

    def send(_self, method, url, **kwargs):
        captured.append((url, kwargs))
        response = requests.Response()
        response.status_code = 201
        return response

    monkeypatch.setattr(requests.Session, "request", send)
    WebPush(organizer, None).send(subscription(), {"body": "synthetic private reminder"})
    url, payload = captured[0]
    assert url.startswith("https://fcm.googleapis.com/")
    assert payload["allow_redirects"] is False
    assert b"synthetic private reminder" not in payload["data"]
    assert payload["headers"]["authorization"].startswith("vapid ")


@pytest.mark.asyncio
async def test_push_reaches_chat_reminders_beyond_first_page(organizer, tmp_path):
    outbox = NotificationStore(tmp_path / "push.sqlite3")
    outbox.register("remote:device1:chat")
    organizer.capabilities = SimpleNamespace(
        outbox=outbox, preferences=SimpleNamespace(quiet=lambda h: False)
    )
    push = WebPush(organizer, SimpleNamespace(get_device=lambda d: True))
    push.subscribe(subscription(), "remote:device1:inbox", "device1")
    push.send = Mock()
    for i in range(105):
        outbox.publish(
            "remote:device1:chat",
            {"event": "reminder", "id": str(i), "created_at": datetime.now(UTC).isoformat()},
        )
    await push.deliver()
    assert push.send.call_count == 105
    await push.deliver()
    assert push.send.call_count == 105


def test_remote_organizer_authorization_and_capture_visibility(organizer, monkeypatch):
    from dataclasses import replace

    settings = replace(
        organizer.config,
        remote_access_enabled=True,
        remote_origin="https://jarvis.test-tail.ts.net",
        remote_allowed_login="owner@example.com",
    )
    app = create_app(settings)
    monkeypatch.setattr(
        "jarvis.services.remote_access.verify_registration_response",
        lambda **kwargs: SimpleNamespace(
            credential_id=b"organizer-fixture", credential_public_key=b"key", sign_count=0
        ),
    )
    base = settings.remote_origin
    headers = {
        "Origin": base,
        "Tailscale-User-Login": "owner@example.com",
        "Tailscale-User-Name": "Owner",
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(base + "/api/organizer/today", headers=headers).status_code == 401
        pairing = client.post("/api/remote/pairing/start").json()
        options = client.post(
            base + "/api/remote/pair/options",
            headers=headers,
            json={"code": pairing["code"], "label": "Synthetic phone"},
        ).json()
        verified = client.post(
            base + "/api/remote/pair/verify",
            headers=headers,
            json={
                "ceremony_id": options["ceremony_id"],
                "credential": {"response": {"transports": ["internal"]}},
            },
        )
        assert verified.status_code == 200
        assert (
            client.post(base + "/api/organizer/calendar/connect", headers=headers).status_code
            == 403
        )
        assert client.post(base + "/api/organizer/backups", headers=headers).status_code == 403
        assert (
            client.post(
                base + "/api/organizer/captures",
                headers={**headers, "Origin": "https://evil.example"},
                json={"text": "Forbidden", "request_id": "a" * 32},
            ).status_code
            == 403
        )
        captured = client.post(
            base + "/api/organizer/captures",
            headers=headers,
            json={"text": "Phone idea", "request_id": "a" * 32},
        )
        assert captured.status_code == 200
        assert client.get("/api/organizer/today").json()["captures"][0]["text"] == "Phone idea"
        client.delete("/api/remote/devices/" + verified.json()["device"]["device_id"])
        assert client.get(base + "/api/organizer/today", headers=headers).status_code == 401


def test_api_review_and_capture_validation(organizer):
    app = create_app(organizer.config)
    with TestClient(app) as client:
        response = client.post(
            "/api/organizer/captures", json={"text": "Idea", "request_id": "a" * 32}
        )
        assert response.status_code == 200
        assert client.get("/api/organizer/today").json()["captures"][0]["text"] == "Idea"
        assert (
            client.post(
                "/api/organizer/captures", json={"text": "  ", "request_id": "b" * 32}
            ).status_code
            == 400
        )
        assert client.post("/api/organizer/proposals/missing/publish", json={}).status_code == 422
        assert (
            client.post(
                "/api/organizer/study", json={"title": "Test", "deadline": "2000-01-01"}
            ).status_code
            == 400
        )
