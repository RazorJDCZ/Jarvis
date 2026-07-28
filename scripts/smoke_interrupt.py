from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from jarvis.config import Settings
from jarvis.providers.stt import WhisperTranscriber
from jarvis.providers.tts import PiperTTS
from jarvis.services.interruptions import VoiceInterruptionMatcher


async def verify() -> dict[str, object]:
    settings = Settings()
    audio = await PiperTTS(settings).synthesize("Jarvis, es suficiente")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
            audio_file.write(audio)
            temporary = Path(audio_file.name)
        transcript, language = await WhisperTranscriber(settings).transcribe(temporary)
        return {
            "audio_generated": len(audio) > 44,
            "transcript": transcript,
            "language": language,
            "interruption_recognized": VoiceInterruptionMatcher(settings.wake_word).matches(
                transcript
            ),
        }
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
