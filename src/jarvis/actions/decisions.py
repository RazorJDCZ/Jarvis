from __future__ import annotations

import re
from enum import StrEnum

from jarvis.actions.parser import normalize_request


class ActionDecision(StrEnum):
    NONE = "none"
    APPROVE = "approve"
    REJECT = "reject"


class ActionDecisionInterpreter:
    """Interpret bounded natural confirmations without treating new commands as approval."""

    _APPROVAL = re.compile(
        r"^(?:"
        r"(?:si|claro(?: que si)?|de acuerdo|correcto|esta bien)"
        r"(?:\s+(?:por favor|esta bien|puedes hacerlo|hazlo|procede|adelante|dale|"
        r"confirmo|confirma|autorizo|quiero que lo hagas|puedes proceder)){0,3}|"
        r"adelante|dale|hazlo|procede|autorizo|confirmo|confirmado|confirma|"
        r"confirma siempre|autoriza siempre|siempre permite|permite siempre"
        r")$"
    )
    _REJECTION = re.compile(
        r"^(?:no(?:\s+(?:gracias|mejor no|lo hagas|cancelalo|lo autorices))?|"
        r"mejor no|no lo hagas|no gracias|cancela|cancelalo|cancelar|cancelado|"
        r"olvidalo|detente|rechaza|rechazalo)$"
    )

    @classmethod
    def interpret(cls, message: str) -> ActionDecision:
        normalized = normalize_request(message)
        normalized = re.sub(r"[,;.!?]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized or len(normalized.split()) > 12:
            return ActionDecision.NONE
        if cls._APPROVAL.fullmatch(normalized):
            return ActionDecision.APPROVE
        if cls._REJECTION.fullmatch(normalized):
            return ActionDecision.REJECT
        return ActionDecision.NONE
