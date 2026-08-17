from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.capabilities.stores import (
    KnowledgeStore,
    PermissionStore,
    ReminderStore,
    TraceStore,
)


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_trace_lifecycle_is_ordered_bounded_redacted_and_session_isolated(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
    store = TraceStore(tmp_path / "stores.sqlite3", clock=clock, max_spans=2)
    trace_id = store.start(
        "phone",
        "Busca algo con password=hunter2 " + "x" * 600,
        "VOICE",
    )
    assert store.add_span(
        trace_id,
        "intent",
        "completed",
        "token=abc123 listo",
        {"level": 42, "token": "abc123", "nested": {"password": "hunter2"}},
    )
    clock.value += timedelta(seconds=1)
    assert store.add_span(
        trace_id,
        "screen",
        "completed",
        "contenido privado",
        {"image": "raw pixels"},
        sensitive=True,
    )
    assert store.add_span(trace_id, "extra", "completed") is False
    assert store.finish(trace_id, "completed") is True

    trace = store.get(trace_id, "phone")

    assert trace is not None
    assert trace.status == "completed"
    assert trace.channel == "voice"
    assert "hunter2" not in trace.input_summary
    assert len(trace.input_summary) <= 500
    assert [span.sequence for span in trace.spans] == [1, 2]
    assert "abc123" not in trace.spans[0].detail
    assert trace.spans[0].metadata["token"] == "<redacted>"
    assert trace.spans[1].detail == "<redacted>"
    assert trace.spans[1].metadata == {"redacted": True}
    assert store.get(trace_id, "another-session") is None
    assert store.recent("another-session", 10) == ()
    assert store.recent("phone", 10)[0].trace_id == trace_id


def test_trace_rejects_invalid_bounds_and_unknown_ids(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.sqlite3")

    with pytest.raises(ValueError, match="session_id"):
        store.start("x" * 129, "input", "chat")
    with pytest.raises(ValueError, match="input_summary"):
        store.start("a", "   ", "chat")
    assert store.add_span("missing", "step", "ok") is False
    assert store.finish("missing", "failed") is False


def test_trace_history_prunes_oldest_records_per_session(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "trace.sqlite3", max_records_per_session=10)
    trace_ids = [store.start("phone", f"request {index}", "chat") for index in range(12)]

    assert len(store.recent("phone", 100)) == 10
    assert store.get(trace_ids[0], "phone") is None
    assert store.get(trace_ids[-1], "phone") is not None


def test_permissions_are_scoped_expirable_and_never_override_high_risk(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
    store = PermissionStore(tmp_path / "permissions.sqlite3", clock=clock)
    store.set("media.play_pause", False, "allow")
    store.set(
        "clipboard.read",
        True,
        "allow",
        expires_at=clock.value + timedelta(minutes=5),
    )
    store.set("window.close", False, "ask")

    assert store.is_allowed("media.play_pause", False, "low") is True
    assert store.is_allowed("media.play_pause", True, "low") is False
    assert store.is_allowed("window.close", False, "medium") is False
    assert store.is_allowed("media.play_pause", False, "high") is False
    assert store.is_allowed("media.play_pause", False, "blocked") is False
    assert store.is_allowed("clipboard.read", True, "medium") is True

    clock.value += timedelta(minutes=6)

    assert store.is_allowed("clipboard.read", True, "medium") is False
    assert {rule.action for rule in store.list()} == {"media.play_pause", "window.close"}
    assert store.delete("media.play_pause", False) is True
    assert store.delete("media.play_pause", False) is False


def test_permission_validation_fails_closed(tmp_path: Path) -> None:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    store = PermissionStore(tmp_path / "permissions.sqlite3", clock=lambda: now)

    with pytest.raises(ValueError, match="allow.*ask"):
        store.set("browser.open", False, "always")
    with pytest.raises(ValueError, match="futuro"):
        store.set("browser.open", False, "allow", expires_at=now)
    assert store.is_allowed("missing.action", False, "low") is False


def test_reminders_are_due_session_isolated_and_soft_cancelled(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
    store = ReminderStore(tmp_path / "reminders.sqlite3", clock=clock)
    first = store.create("a", "Entregar proyecto", clock.value - timedelta(minutes=1))
    other = store.create("b", "Privado", clock.value - timedelta(minutes=1))

    assert [item.reminder_id for item in store.due("a")] == [first.reminder_id]
    assert all(item.reminder_id != other.reminder_id for item in store.list("a"))
    fired = store.mark_fired(first.reminder_id, "a")
    assert fired is not None and fired.last_fired_at is not None
    assert store.due("a") == ()
    assert store.cancel(other.reminder_id, "a") is False
    assert store.cancel(other.reminder_id, "b") is True
    assert store.list("b") == ()
    assert store.list("b", include_cancelled=True)[0].cancelled_at is not None


@pytest.mark.parametrize(
    ("recurrence", "due", "fired", "expected"),
    [
        (
            "daily",
            datetime(2026, 8, 1, 9, tzinfo=UTC),
            datetime(2026, 8, 3, 10, tzinfo=UTC),
            datetime(2026, 8, 4, 9, tzinfo=UTC),
        ),
        (
            "weekly",
            datetime(2026, 8, 1, 9, tzinfo=UTC),
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            datetime(2026, 8, 15, 9, tzinfo=UTC),
        ),
        (
            "monthly",
            datetime(2027, 1, 31, 9, tzinfo=UTC),
            datetime(2027, 2, 28, 10, tzinfo=UTC),
            datetime(2027, 3, 31, 9, tzinfo=UTC),
        ),
    ],
)
def test_recurring_reminder_advances_to_the_first_future_occurrence(
    tmp_path: Path,
    recurrence: str,
    due: datetime,
    fired: datetime,
    expected: datetime,
) -> None:
    store = ReminderStore(tmp_path / f"{recurrence}.sqlite3", clock=lambda: fired)
    reminder = store.create("a", "Recurrente", due, recurrence)

    advanced = store.mark_fired(reminder.reminder_id, "a", fired)

    assert advanced is not None
    assert datetime.fromisoformat(advanced.due_at) == expected


def test_reminder_bounds_and_traversal_like_text_have_no_path_semantics(tmp_path: Path) -> None:
    clock = datetime(2026, 8, 10, tzinfo=UTC)
    store = ReminderStore(
        tmp_path / "reminders.sqlite3",
        clock=lambda: clock,
        max_per_session=1,
    )
    reminder = store.create("a", "../../no-es-un-archivo", clock + timedelta(hours=1))

    assert reminder.title == "../../no-es-un-archivo"
    assert not (tmp_path.parent / "no-es-un-archivo").exists()
    with pytest.raises(ValueError, match="límite"):
        store.create("a", "Segundo", clock + timedelta(hours=2))
    with pytest.raises(ValueError, match="Recurrencia"):
        ReminderStore(tmp_path / "other.sqlite3").create(
            "a",
            "Inválido",
            clock,
            "hourly",
        )


def test_knowledge_search_returns_grounded_excerpt_and_is_session_isolated(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    source = store.upsert_source(
        "owner",
        "Apuntes de Python",
        "Los decoradores de Python envuelven funciones para ampliar su comportamiento.",
        "onenote://programacion",
    )
    store.upsert_source(
        "other",
        "Secreto",
        "La palabra confidencial es decoradores.",
        "private://other",
    )

    results = store.search("owner", "decoradores Python")

    assert len(results) == 1
    assert results[0].source_id == source.source_id
    assert "decoradores" in results[0].excerpt
    assert results[0].citation == "Apuntes de Python — onenote://programacion"
    assert store.search("missing", "decoradores") == ()
    assert [item.title for item in store.list_sources("owner")] == ["Apuntes de Python"]


def test_knowledge_upsert_replaces_same_origin_without_duplicates(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    first = store.upsert_source("a", "Viejo", "contenido anterior", "manual://uno")
    second = store.upsert_source("a", "Nuevo", "contenido actualizado", "manual://uno")

    assert second.source_id == first.source_id
    assert len(store.list_sources("a")) == 1
    assert store.search("a", "actualizado")[0].title == "Nuevo"
    assert store.search("a", "anterior") == ()


def test_knowledge_like_fallback_handles_queries_and_traversal_as_plain_data(
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(tmp_path / "fallback.sqlite3", enable_fts=False)
    source = store.upsert_source(
        "a",
        "Minecraft 100%",
        "Una guía sobre redstone y construcción segura.",
        "../../documento.txt",
    )

    result = store.search("a", "redstone")

    assert store.fts_available is False
    assert result[0].source_id == source.source_id
    assert result[0].origin == "../../documento.txt"
    assert not (tmp_path.parent / "documento.txt").exists()
    assert store.search("a", "%_") == ()


def test_knowledge_bounds_reject_empty_or_oversized_input(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")

    with pytest.raises(ValueError, match="text"):
        store.upsert_source("a", "Título", "", "manual://a")
    with pytest.raises(ValueError, match="1000000"):
        store.upsert_source("a", "Título", "x" * 1_000_001, "manual://a")
    with pytest.raises(ValueError, match="query"):
        store.search("a", " ")


def test_knowledge_source_limit_allows_updates_but_blocks_growth(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3", max_sources_per_session=1)
    first = store.upsert_source("a", "Primero", "contenido", "manual://uno")

    updated = store.upsert_source("a", "Actualizado", "contenido nuevo", "manual://uno")
    assert updated.source_id == first.source_id
    with pytest.raises(ValueError, match="límite"):
        store.upsert_source("a", "Segundo", "otro contenido", "manual://dos")
    assert store.upsert_source("b", "Separado", "contenido", "manual://dos")
