"""Real local smoke test: Piper -> WAV -> Faster Whisper -> text."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from jarvis.config import Settings
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS


async def main() -> None:
    settings = Settings()
    tts = PiperTTS(settings)
    stt = WhisperTranscriber(settings)

    print((await tts.status()).model_dump_json())
    print((await stt.status()).model_dump_json())

    audio = await tts.synthesize("Hola Juandi. La prueba de voz local funciona correctamente.")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio)
            temp_path = Path(temp_file.name)
        transcript, language = await stt.transcribe(temp_path)
        print(f"Generated WAV bytes: {len(audio)}")
        print(f"Detected language: {language}")
        print(f"Transcript: {transcript}")
        if not transcript:
            raise RuntimeError("Whisper did not return a transcript")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
