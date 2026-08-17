from __future__ import annotations

import pytest

from jarvis.services.analysis import AnalysisChoice, AnalysisCoordinator


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Sí, profundiza", True),
        ("Quiero una respuesta extensa", True),
        ("Sí, quiero que profundices bastante en la respuesta", True),
        ("No, dame la versión nomal", False),
        ("Prefiero la versión normal y más rápida", False),
        ("No profundices", False),
        ("Quiero hablar de otra cosa", None),
    ],
)
def test_analysis_choice_accepts_natural_bounded_answers(
    phrase: str,
    expected: bool | None,
) -> None:
    assert AnalysisCoordinator.decision(phrase) is expected


def test_pending_analysis_is_replayed_once_and_isolated_by_session() -> None:
    coordinator = AnalysisCoordinator(ttl_seconds=60, max_sessions=2)
    coordinator.remember("one", "Analiza a Emi")
    coordinator.remember("two", "Analízame")

    deep = coordinator.resolve("one", "Sí, hazlo a profundidad")
    untouched = coordinator.resolve("missing", "versión normal")
    normal = coordinator.resolve("two", "No, normal")

    assert deep.choice is AnalysisChoice.DEEP
    assert deep.request == "Analiza a Emi"
    assert untouched.choice is AnalysisChoice.NONE
    assert normal.choice is AnalysisChoice.NORMAL
    assert normal.request == "Analízame"
    assert coordinator.resolve("one", "sí").choice is AnalysisChoice.NONE


def test_ambiguous_choice_keeps_request_but_a_new_question_supersedes_it() -> None:
    coordinator = AnalysisCoordinator(ttl_seconds=60, max_sessions=2)
    coordinator.remember("one", "¿Qué opinas de Montoya?")

    unclear = coordinator.resolve("one", "La versión detalladita")
    assert unclear.choice is AnalysisChoice.CLARIFY
    assert unclear.request == "¿Qué opinas de Montoya?"

    replaced = coordinator.resolve("one", "¿Cuál es el volumen actual?")
    assert replaced.choice is AnalysisChoice.NONE
    assert coordinator.resolve("one", "versión normal").choice is AnalysisChoice.NONE


def test_pending_analysis_capacity_evicts_the_oldest_session() -> None:
    coordinator = AnalysisCoordinator(ttl_seconds=60, max_sessions=2)
    coordinator.remember("one", "primera")
    coordinator.remember("two", "segunda")
    coordinator.remember("three", "tercera")

    assert coordinator.resolve("one", "normal").choice is AnalysisChoice.NONE
    assert coordinator.resolve("two", "normal").request == "segunda"
