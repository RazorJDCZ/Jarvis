from __future__ import annotations

from datetime import datetime

from jarvis.services.commands import SafeCommandRouter, normalize_command


def build_router() -> SafeCommandRouter:
    return SafeCommandRouter(now=lambda: datetime(2026, 7, 17, 22, 30))


def test_informational_commands_are_local_and_deterministic() -> None:
    router = build_router()

    assert router.try_handle("¿Qué hora es?").response == "Son las 22:30."
    assert router.try_handle("dime la fecha").response == ("Hoy es viernes, 17 de julio de 2026.")
    assert "etapa dos" in router.try_handle("¿Cuál es tu versión?").response
    assert "aplicaciones" in router.try_handle("ayuda").response


def test_reset_command_requests_history_and_pending_action_removal() -> None:
    result = build_router().try_handle("Jarvis, olvida esta conversación")

    assert result is not None
    assert result.reset_history is True


def test_unmatched_command_is_delegated() -> None:
    assert build_router().try_handle("cuéntame algo") is None


def test_normalization_removes_wake_prefix_accents_and_extra_spaces() -> None:
    assert normalize_command("  OYE   JÁRVIS,  Sube   el VOLUMEN. ") == "sube el volumen"
