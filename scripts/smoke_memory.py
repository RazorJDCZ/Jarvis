from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from jarvis.config import Settings
from jarvis.services.memory import MemoryService


def verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="jarvis-memory-") as temporary:
        settings = Settings(project_root=Path(temporary), memory_enabled=True)
        first = MemoryService(settings)
        explicit = first.handle("old", "Recuerda que mi color favorito es el azul")
        learned = first.learn("Me gusta tocar el ukelele")
        turn_saved = first.remember_exchange(
            "old",
            "Estoy creando mi propio Jarvis",
            "Es un proyecto ambicioso y muy personal.",
        )
        secret = first.handle("old", "Recuerda que mi contraseña es secreta")

        restarted = MemoryService(settings)
        context = restarted.context("Hablemos del ukelele")
        recent = restarted.recent_context("new")
        clear_request = restarted.handle("new", "Borra toda tu memoria")
        clear_result = restarted.handle("new", "confirmo borrar toda mi memoria")
        with closing(sqlite3.connect(settings.memory_path)) as connection:
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])

        return {
            "database_created": settings.memory_path.is_file(),
            "explicit_saved": explicit is not None and "Guardé" in explicit,
            "implicit_saved": learned is not None,
            "turn_saved": turn_saved,
            "secret_rejected": secret is not None and "No guardaré" in secret,
            "relevant_after_restart": "ukelele" in context,
            "recent_after_restart": "creando mi propio Jarvis" in recent,
            "clear_requires_confirmation": clear_request is not None
            and "confirmo" in clear_request,
            "clear_completed": clear_result is not None and "Eliminé" in clear_result,
            "counts_after_clear": restarted.store.counts(),
            "integrity": integrity,
        }


def main() -> None:
    print(json.dumps(verify(), ensure_ascii=False))


if __name__ == "__main__":
    main()
