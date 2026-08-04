from jarvis.services.wake import WakeGate


def test_push_to_talk_does_not_require_wake_word() -> None:
    gate = WakeGate("jarvis")

    result = gate.evaluate("a", "Cuéntame algo interesante", require_wake_word=False)

    assert result.accepted is True
    assert result.command == "Cuéntame algo interesante"


def test_wake_word_and_command_in_same_phrase() -> None:
    gate = WakeGate("jarvis")

    result = gate.evaluate("a", "Oye Jarvis, ¿quién eres?", require_wake_word=True, now=100)

    assert result.accepted is True
    assert result.activated is True
    assert result.needs_command is False
    assert result.command == "¿quién eres?"


def test_wake_word_arms_next_utterance() -> None:
    gate = WakeGate("jarvis", window_seconds=10)

    activation = gate.evaluate("a", "Jarvis", require_wake_word=True, now=100)
    command = gate.evaluate("a", "Dime la hora", require_wake_word=True, now=104)

    assert activation.needs_command is True
    assert command.accepted is True
    assert command.command == "Dime la hora"


def test_unaddressed_speech_is_ignored() -> None:
    gate = WakeGate("jarvis")

    result = gate.evaluate("a", "Esto no era para ti", require_wake_word=True, now=100)

    assert result.accepted is False


def test_armed_window_expires() -> None:
    gate = WakeGate("jarvis", window_seconds=10)
    gate.evaluate("a", "Jarvis", require_wake_word=True, now=100)

    result = gate.evaluate("a", "Dime la hora", require_wake_word=True, now=111)

    assert result.accepted is False


def test_armed_window_is_isolated_per_session() -> None:
    gate = WakeGate("jarvis", window_seconds=10)
    gate.evaluate("a", "Jarvis", require_wake_word=True, now=100)

    other_session = gate.evaluate("b", "Dime la hora", require_wake_word=True, now=101)

    assert other_session.accepted is False


def test_wake_word_is_case_and_accent_insensitive() -> None:
    gate = WakeGate("járvis")

    result = gate.evaluate("a", "OYE JARVIS: abre la calculadora", True, now=100)

    assert result.accepted is True
    assert result.command == "abre la calculadora"


def test_known_spanish_whisper_wake_variants_are_accepted() -> None:
    gate = WakeGate("jarvis")

    for transcript in (
        "Carvis, cuéntame una historia",
        "Harvis dime la hora",
        "Garvis abre la calculadora",
        "Yarvis, ¿qué ves?",
    ):
        result = gate.evaluate(transcript, transcript, True, now=100)
        assert result.accepted is True
        assert result.activated is True


def test_unrelated_near_matches_do_not_activate_jarvis() -> None:
    gate = WakeGate("jarvis")

    for transcript in ("Carlos dime la hora", "Travis abre Chrome", "avisa mañana"):
        assert gate.evaluate(transcript, transcript, True, now=100).accepted is False


def test_empty_transcript_is_ignored_in_every_mode() -> None:
    gate = WakeGate("jarvis")

    assert gate.evaluate("a", "   ", False).accepted is False
    assert gate.evaluate("a", "   ", True).accepted is False


def test_wake_sessions_are_capped_and_expired_entries_are_removed() -> None:
    gate = WakeGate("jarvis", window_seconds=10, max_sessions=2)
    gate.evaluate("a", "Jarvis", True, now=100)
    gate.evaluate("b", "Jarvis", True, now=101)
    gate.evaluate("c", "Jarvis", True, now=102)

    assert set(gate._armed_until) == {"b", "c"}

    gate.evaluate("d", "no era para ti", True, now=113)

    assert gate._armed_until == {}
