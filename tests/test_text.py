from jarvis.text import strip_emojis


def test_strip_emojis_preserves_spoken_symbols_and_punctuation() -> None:
    assert strip_emojis("Listo 😏. Temperatura: 20 °C ✅") == "Listo. Temperatura: 20 °C"
    assert strip_emojis("Guardado en .data/mail.sqlite3.") == "Guardado en .data/mail.sqlite3."


def test_strip_emojis_handles_joined_and_flag_sequences() -> None:
    assert strip_emojis("Familia 👨‍👩‍👧‍👦 y bandera 🇪🇨.") == "Familia y bandera."


def test_streaming_emoji_cleanup_preserves_chunk_boundaries() -> None:
    assert strip_emojis(" hola 😏 ", trim=False) == " hola  "
