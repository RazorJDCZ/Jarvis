from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum

from jarvis.actions.parser import normalize_request


class AnalysisChoice(StrEnum):
    """Result of interpreting a reply to the normal/deep analysis prompt."""

    NONE = "none"
    NORMAL = "normal"
    DEEP = "deep"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class PendingAnalysis:
    request: str
    created_at: float


@dataclass(frozen=True, slots=True)
class AnalysisResolution:
    choice: AnalysisChoice
    request: str = ""


class AnalysisCoordinator:
    """Own analytical-intent detection and its bounded confirmation state.

    ConversationService used to combine regex classification, pending-state eviction and
    recursive replay in one large method. Keeping those decisions here makes the transition
    rules explicit and independently testable.
    """

    _ANALYTICAL_INTENT = re.compile(
        r"\b(?:analiza|analizame|analizar|analisis|profundiza|profundizar|reflexiona|"
        r"reflexionar|evalua|evaluame|evaluar|valoracion|compara|comparar|comparacion|"
        r"interpreta|interpretame|interpretar|"
        r"como describirias|que opinas|que piensas|que crees|por que crees|que puedes inferir|"
        r"que conclusion|fortalezas|debilidades|personalidad|dinamica|implicaciones|"
        r"perspectivas|puntos de vista|pros y contras)\b",
        flags=re.IGNORECASE,
    )
    _EXPLICIT_DEEP_ANALYSIS = re.compile(
        r"\b(?:analisis profundo|modo profundo|a fondo|en profundidad|profundiza|"
        r"respuesta (?:muy )?(?:larga|extensa|detallada)|con (?:mucho|gran) detalle|"
        r"detalladamente)\b",
        flags=re.IGNORECASE,
    )
    _PERSON_ANALYSIS_INTENT = re.compile(
        r"\b(?:que sabes (?:de|sobre)|cuentame (?:sobre|de)|hablame (?:sobre|de)|"
        r"dime algo (?:sobre|de)|que puedes decir (?:sobre|de)|describeme|como es|"
        r"como soy|como (?:dirias|crees) que soy|"
        r"como me (?:ves|describirias|definirias|percibes)|"
        r"que (?:tipo|clase) de persona (?:crees que )?soy|"
        r"que impresion tienes de|que imagen tienes de|cual es tu lectura (?:de|sobre))\b",
        flags=re.IGNORECASE,
    )
    _COMPUTER_ANALYSIS_TARGET = re.compile(
        r"\b(?:computadora|ordenador|pc|escritorio|monitor(?:es)?|pantalla(?:s)?|"
        r"ventana(?:s)?|aplicacion(?:es)?|apps?|programa(?:s)?|navegador|chrome|edge|"
        r"brave|pestana(?:s)?|pagina(?:s)? web|sitio(?:s)? web|archivo(?:s)?|carpeta(?:s)?|"
        r"documento(?:s)?|portapapeles|captura(?:s)?|imagen(?:es)?|interfaz|boton(?:es)?|"
        r"dialogo|error(?:es)?|correo(?:s)?|email|mensaje(?:s)?)\b",
        flags=re.IGNORECASE,
    )
    _DEEP_CONFIRMATION = re.compile(
        r"^(?:si(?:\s*,?\s*(?:por favor|profundiza|hazlo|dale|adelante))?|claro|dale|"
        r"adelante|hazlo|profundiza|modo profundo|quiero (?:la|una) (?:larga|extensa)|"
        r"dame (?:la|una) (?:larga|extensa))$",
        flags=re.IGNORECASE,
    )
    _NORMAL_CONFIRMATION = re.compile(
        r"^(?:no(?:\s*,?\s*(?:gracias|normal|breve|corta|version normal|dame la "
        r"version normal))?|normal|breve|corta|version normal|respuesta normal|"
        r"dame la version normal|hazlo breve)$",
        flags=re.IGNORECASE,
    )
    _FLEXIBLE_DEEP_POSITIVE = re.compile(
        r"\b(?:si|claro|dale|adelante|hazlo|continua|continuemos|por supuesto|"
        r"de acuerdo|correcto|listo|profundiza|profundices|profundo|profunda|"
        r"larga|extensa|detallada|mas detalle)\b",
        flags=re.IGNORECASE,
    )
    _FLEXIBLE_DEEP_NEGATIVE = re.compile(
        r"\b(?:no|normal|breve|corta|corto|rapida|rapido|sin profundizar|"
        r"no profundices|menos detalle)\b",
        flags=re.IGNORECASE,
    )
    _DECISION_CUE = re.compile(
        r"\b(?:si|no|claro|dale|adelante|hazlo|continua|listo|quiero|prefiero|"
        r"profund|normal|breve|cort|larg|extens|detall|rapi|detalle)\w*\b",
        flags=re.IGNORECASE,
    )

    def __init__(self, *, ttl_seconds: float, max_sessions: int) -> None:
        self.ttl_seconds = max(1.0, ttl_seconds)
        self.max_sessions = max(1, max_sessions)
        self._pending: OrderedDict[str, PendingAnalysis] = OrderedDict()

    @classmethod
    def decision(cls, message: str) -> bool | None:
        normalized = normalize_request(message)
        if cls._DEEP_CONFIRMATION.fullmatch(normalized):
            return True
        if cls._NORMAL_CONFIRMATION.fullmatch(normalized):
            return False

        negative = cls._FLEXIBLE_DEEP_NEGATIVE.search(normalized)
        positive = cls._FLEXIBLE_DEEP_POSITIVE.search(normalized)
        if negative and (
            normalized.startswith("no")
            or re.search(r"\b(?:normal|breve|cort[ao]|rapid[ao]|sin profundizar)\b", normalized)
        ):
            return False
        if positive and (
            re.match(
                r"^(?:si|claro|dale|adelante|hazlo|continua|continuemos|por supuesto|"
                r"de acuerdo|correcto|listo)\b",
                normalized,
            )
            or re.search(
                r"\b(?:profundiza|profundices|profund[ao]|modo profundo|"
                r"respuesta (?:larga|extensa)|(?:la|una) (?:larga|extensa)|"
                r"mas detalle|muy detallada)\b",
                normalized,
            )
        ):
            return True
        return None

    @classmethod
    def looks_like_decision(cls, message: str) -> bool:
        normalized = normalize_request(message)
        return bool(cls._DECISION_CUE.search(normalized) and len(normalized.split()) <= 24)

    @classmethod
    def looks_analytical(cls, message: str) -> bool:
        normalized = normalize_request(message)
        if cls._DEEP_CONFIRMATION.fullmatch(normalized) or cls._NORMAL_CONFIRMATION.fullmatch(
            normalized
        ):
            return False
        return bool(cls._ANALYTICAL_INTENT.search(normalized))

    @classmethod
    def requests_deep_analysis(cls, message: str) -> bool:
        normalized = normalize_request(message)
        return bool(
            not cls._DEEP_CONFIRMATION.fullmatch(normalized)
            and cls._EXPLICIT_DEEP_ANALYSIS.search(normalized)
        )

    @classmethod
    def is_person_analysis_phrase(cls, message: str) -> bool:
        return bool(cls._PERSON_ANALYSIS_INTENT.search(normalize_request(message)))

    @classmethod
    def is_computer_analysis(cls, message: str) -> bool:
        return bool(cls._COMPUTER_ANALYSIS_TARGET.search(normalize_request(message)))

    def _prune(self) -> None:
        expires_before = time.monotonic() - self.ttl_seconds
        expired = [
            session_id
            for session_id, pending in self._pending.items()
            if pending.created_at < expires_before
        ]
        for session_id in expired:
            self._pending.pop(session_id, None)

    def remember(self, session_id: str, message: str) -> None:
        self._prune()
        self._pending[session_id] = PendingAnalysis(message.strip(), time.monotonic())
        self._pending.move_to_end(session_id)
        while len(self._pending) > self.max_sessions:
            self._pending.popitem(last=False)

    def resolve(self, session_id: str, message: str) -> AnalysisResolution:
        """Resolve one state transition and discard superseded requests.

        A clearly unrelated message replaces the old analytical choice. An ambiguous short
        answer keeps it pending so a second clarification cannot accidentally replay old chat.
        """
        self._prune()
        pending = self._pending.get(session_id)
        if pending is None:
            return AnalysisResolution(AnalysisChoice.NONE)
        decision = self.decision(message)
        if decision is not None:
            self._pending.pop(session_id, None)
            return AnalysisResolution(
                AnalysisChoice.DEEP if decision else AnalysisChoice.NORMAL,
                pending.request,
            )
        if self.looks_like_decision(message):
            return AnalysisResolution(AnalysisChoice.CLARIFY, pending.request)
        self._pending.pop(session_id, None)
        return AnalysisResolution(AnalysisChoice.NONE)

    def reset(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
