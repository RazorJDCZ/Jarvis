import pytest

from jarvis.services.interruptions import VoiceInterruptionMatcher


@pytest.mark.parametrize(
    "phrase",
    [
        "Jarvis, es suficiente",
        "Oye Járvis, detente",
        "Jarvis deja de hablar",
        "JARVIS BASTA",
        "Jarvis, cállate",
        "Jarvis ya",
    ],
)
def test_explicit_wake_word_interruption_phrases_are_recognized(phrase: str) -> None:
    assert VoiceInterruptionMatcher("jarvis").matches(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "es suficiente",
        "deja de hablar",
        "Jarvis cuéntame algo",
        "creo que ya es suficiente información",
        "el nombre Jarvis aparece en la respuesta",
    ],
)
def test_unaddressed_or_conversational_phrases_never_interrupt(phrase: str) -> None:
    assert VoiceInterruptionMatcher("jarvis").matches(phrase) is False
