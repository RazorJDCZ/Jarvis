from __future__ import annotations

import pytest

from jarvis.actions.decisions import ActionDecision, ActionDecisionInterpreter


@pytest.mark.parametrize(
    "phrase",
    (
        "sí",
        "Sí, está bien",
        "Claro que sí, por favor",
        "De acuerdo, procede",
        "Sí, por favor, hazlo",
        "Sí, por favor, quiero que lo hagas",
        "autorizo",
    ),
)
def test_natural_action_approvals_are_bounded(phrase: str) -> None:
    assert ActionDecisionInterpreter.interpret(phrase) is ActionDecision.APPROVE


@pytest.mark.parametrize(
    "phrase",
    (
        "no",
        "No, gracias",
        "No, mejor no",
        "No lo hagas",
        "No, cancélalo",
        "olvídalo",
    ),
)
def test_natural_action_rejections_are_bounded(phrase: str) -> None:
    assert ActionDecisionInterpreter.interpret(phrase) is ActionDecision.REJECT


@pytest.mark.parametrize(
    "phrase",
    (
        "sí, pero abre la calculadora",
        "no sé si hacerlo",
        "quiero que abras Chrome",
        "claro, explícame qué pasaría",
        "sí " + "por favor " * 20,
    ),
)
def test_new_or_ambiguous_requests_are_not_action_confirmations(phrase: str) -> None:
    assert ActionDecisionInterpreter.interpret(phrase) is ActionDecision.NONE
