from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from jarvis.actions.parser import DeterministicActionParser
from jarvis.actions.planner import LocalActionPlanner
from jarvis.actions.retrieval import CapabilityRetriever
from jarvis.config import Settings
from jarvis.services.agent_state import AgentStateStore, StoredGoal


@pytest.mark.parametrize(
    "fixture_name", ["agent_intents.json", "agent_intents_adversarial.json"]
)
def test_real_language_corpus_retrieves_expected_capability(fixture_name: str) -> None:
    cases = json.loads(
        (Path(__file__).parent / "fixtures" / fixture_name).read_text(encoding="utf-8")
    )
    names = tuple(LocalActionPlanner._TOOL_GUIDE)
    retriever = CapabilityRetriever(names, LocalActionPlanner._TOOL_GUIDE)

    missed = [
        (case["text"], case["tool"], retriever.select(case["text"], limit=12))
        for case in cases
        if case["tool"] not in retriever.select(case["text"], limit=12)
    ]

    assert missed == []


def test_every_documented_capability_can_retrieve_itself_without_pinning() -> None:
    names = tuple(LocalActionPlanner._TOOL_GUIDE)
    retriever = CapabilityRetriever(names, LocalActionPlanner._TOOL_GUIDE)

    missed = {
        name: retriever.select(description, limit=12)
        for name, description in LocalActionPlanner._TOOL_GUIDE.items()
        if name not in retriever.select(description, limit=12)
    }

    assert missed == {}


def test_semantic_retrieval_is_deterministic_unique_and_bounded() -> None:
    names = tuple(LocalActionPlanner._TOOL_GUIDE)
    retriever = CapabilityRetriever(names, LocalActionPlanner._TOOL_GUIDE)
    request = "Compara mis tareas con la agenda y recomiéndame qué hacer primero"

    first = retriever.select(request, limit=18)
    second = retriever.select(request, limit=18)

    assert first == second
    assert len(first) == 18
    assert len(set(first)) == len(first)
    assert {"task.list", "calendar.list", "appa.briefing"}.issubset(first)


def test_semantic_markers_match_words_or_stems_but_not_arbitrary_substrings() -> None:
    assert CapabilityRetriever._marker_present("dia", "resumen del dia") is True
    assert CapabilityRetriever._marker_present("dia", "avisame en media hora") is False
    assert CapabilityRetriever._marker_present("abiert*", "ventanas abiertas") is True
    assert CapabilityRetriever._marker_present("abiert*", "biblioteca") is False


def test_every_natural_language_case_can_reach_the_semantic_planner() -> None:
    parser = DeterministicActionParser()
    planner = LocalActionPlanner(
        Settings(agent_reasoning_enabled=False), tuple(LocalActionPlanner._TOOL_GUIDE)
    )
    cases: list[dict[str, str]] = []
    for fixture_name in ("agent_intents.json", "agent_intents_adversarial.json"):
        cases.extend(
            json.loads(
                (Path(__file__).parent / "fixtures" / fixture_name).read_text(encoding="utf-8")
            )
        )

    unreachable = [
        case["text"]
        for case in cases
        if parser.parse(case["text"]) is None
        and not parser.has_agent_intent(case["text"])
        and (
            parser.is_explicitly_non_action(case["text"])
            or not planner.likely_tool_request(case["text"])
        )
    ]

    assert unreachable == []


@pytest.mark.parametrize(
    "text",
    [
        "No quiero que abras Chrome",
        "Explícame cómo abrir una pestaña",
        "Quiero hablar sobre cómo organizar archivos",
        "Hipotéticamente, si pudieras cerrar una ventana",
    ],
)
def test_semantic_admission_preserves_explicit_non_action_guard(text: str) -> None:
    parser = DeterministicActionParser()

    assert parser.is_explicitly_non_action(text) is True


def test_world_state_is_ttl_bounded_and_never_promotes_model_prose(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    state.observe(
        "session",
        "system.status",
        {"cpu": 21},
        source="trusted-action:system.status",
        ttl_seconds=30,
    )

    facts = state.facts("session")

    assert facts[0].value == {"cpu": 21}
    assert facts[0].source.startswith("trusted-action:")
    assert state.planner_context("session")[0]["request"] == "verified-world-state"


def test_agent_goal_survives_process_memory_restart(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    now = time.time()
    first = AgentStateStore(path)
    first.save_goal(StoredGoal("mobile", "organiza mis ventanas", 2, 3, True, True, now, now))

    restored = AgentStateStore(path).load_goal("mobile", max_age_seconds=900)

    assert restored is not None
    assert restored.original_request == "organiza mis ventanas"
    assert restored.remote is True


def test_agent_state_database_path_is_private_to_project(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)

    assert settings.agent_state_path == tmp_path / ".data" / "agent-state.sqlite3"


def test_world_state_rejects_untrusted_sources_and_invalid_bounds(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "agent.sqlite3")

    with pytest.raises(ValueError, match="fuente"):
        state.observe("session", "claim", "inventado", source="model-response")
    with pytest.raises(ValueError, match="Vigencia"):
        state.observe(
            "session", "system.status", {}, source="trusted-action:system.status", ttl_seconds=0
        )
    with pytest.raises(ValueError, match="Confianza"):
        state.observe(
            "session",
            "system.status",
            {},
            source="trusted-action:system.status",
            confidence=1.1,
        )

    assert state.facts("session") == ()


def test_world_state_expires_isolates_sessions_and_labels_global_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [10_000.0]
    monkeypatch.setattr("jarvis.services.agent_state.time.time", lambda: clock[0])
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    state.observe(
        "alpha", "volume.get", {"level": 20}, source="trusted-action:volume.get", ttl_seconds=10
    )
    state.observe(
        "beta", "volume.get", {"level": 80}, source="trusted-action:volume.get", ttl_seconds=10
    )
    state.observe(
        "*", "system.identity", {"name": "Jarvis"}, source="trusted-system:identity", ttl_seconds=10
    )

    alpha = state.facts("alpha")
    assert {fact.value.get("level") for fact in alpha if "level" in fact.value} == {20}
    assert any(fact.session_id == "*" for fact in alpha)
    assert all(fact.value.get("level") != 80 for fact in alpha)

    clock[0] += 11
    assert state.facts("alpha") == ()


def test_world_state_truncates_large_values_and_skips_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    state = AgentStateStore(path)
    state.observe(
        "session",
        "system.status",
        {"blob": "x" * 40_000},
        source="trusted-action:system.status",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE world_facts SET value_json = ? WHERE fact_key = ?",
            ("{not-json", "system.status"),
        )

    assert state.facts("session") == ()

    state.observe(
        "session",
        "system.status",
        {"blob": "x" * 40_000},
        source="trusted-action:system.status",
    )
    fact = state.facts("session")[0]
    assert fact.value["truncated"] is True
    assert len(fact.value["summary"]) <= 8_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", ""),
        ("original_request", ""),
        ("remaining_rounds", -1),
        ("remaining_rounds", True),
        ("remaining_actions", 513),
        ("continue_after_current", 1),
        ("remote", "yes"),
        ("created_at", float("nan")),
    ],
)
def test_persistent_goal_rejects_invalid_records(
    tmp_path: Path, field: str, value: object
) -> None:
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    now = time.time()
    values: dict[str, object] = {
        "session_id": "session",
        "original_request": "organiza el escritorio",
        "remaining_rounds": 2,
        "remaining_actions": 4,
        "continue_after_current": True,
        "remote": False,
        "created_at": now,
        "updated_at": now,
    }
    values[field] = value

    with pytest.raises(ValueError):
        state.save_goal(StoredGoal(**values))  # type: ignore[arg-type]


def test_persistent_goal_expires_and_corrupt_rows_are_removed(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    state = AgentStateStore(path)
    now = time.time()
    state.save_goal(StoredGoal("old", "objetivo viejo", 2, 3, True, False, now - 50, now - 50))
    assert state.load_goal("old", max_age_seconds=5) is None

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO agent_goals VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("bad", "objetivo", -4, 2, 1, 0, now, now),
        )
    assert state.load_goal("bad", max_age_seconds=60) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_goals WHERE session_id = 'bad'"
        ).fetchone()[0] == 0


def test_persistent_goals_are_bounded_and_latest_value_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AgentStateStore, "_MAX_GOALS", 5)
    path = tmp_path / "agent.sqlite3"
    state = AgentStateStore(path)
    now = time.time()
    for index in range(8):
        state.save_goal(
            StoredGoal(
                f"session-{index}", f"objetivo {index}", 2, 3, True, False, now, now + index
            )
        )
    state.save_goal(StoredGoal("session-7", "objetivo actualizado", 1, 1, True, True, now, now + 9))

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM agent_goals").fetchone()[0] == 5
    restored = AgentStateStore(path).load_goal("session-7", max_age_seconds=60)
    assert restored is not None
    assert restored.original_request == "objetivo actualizado"
    assert restored.remote is True


def test_agent_state_serializes_concurrent_sessions_without_cross_talk(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    now = time.time()

    def write(index: int) -> None:
        session = f"parallel-{index}"
        state.observe(
            session,
            "volume.get",
            {"level": index},
            source="trusted-action:volume.get",
        )
        state.save_goal(StoredGoal(session, f"objetivo {index}", 2, 3, True, False, now, now))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(32)))

    for index in range(32):
        session = f"parallel-{index}"
        assert state.facts(session)[0].value == {"level": index}
        assert state.load_goal(session, max_age_seconds=60).original_request == f"objetivo {index}"


def test_clear_session_deletes_only_its_goal_and_evidence(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    now = time.time()
    for session in ("one", "two"):
        state.observe(
            session, "volume.get", {"session": session}, source="trusted-action:volume.get"
        )
        state.save_goal(StoredGoal(session, f"objetivo {session}", 1, 1, True, False, now, now))

    state.clear_session("one")

    assert state.facts("one") == ()
    assert state.load_goal("one", max_age_seconds=60) is None
    assert state.facts("two")
    assert state.load_goal("two", max_age_seconds=60) is not None
