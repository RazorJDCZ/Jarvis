"""Apply conservative, reversible defaults for the measured desktop."""

from __future__ import annotations

import json
import re
from pathlib import Path

import psutil


def main():
    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    raw = env.read_text(encoding="utf-8")
    backup = root / ".data" / "env-before-assistant-upgrade.env"
    if not backup.exists():
        backup.write_text(raw, encoding="utf-8")
    total = psutil.virtual_memory().total / 1024**3
    values = {
        "JARVIS_ADAPTIVE_RESOURCES": "true",
        "JARVIS_MODEL_RESERVE_GB": "2.5" if total < 24 else "4",
        "JARVIS_REASONING_MIN_FREE_GB": "8.0",
        "JARVIS_STT_CPU_THREADS": str(min(4, psutil.cpu_count(logical=False) or 2)),
        "JARVIS_STT_DEVICE": "auto",
        "JARVIS_VOICE_PRELOAD": "true",
        "JARVIS_SEMANTIC_ENABLED": "true",
        "JARVIS_OLLAMA_WARMUP_ENABLED": "false",
    }
    for name, value in values.items():
        pattern = rf"(?m)^{re.escape(name)}=.*$"
        if re.search(pattern, raw):
            raw = re.sub(pattern, f"{name}={value}", raw)
        else:
            raw = raw.rstrip() + f"\n{name}={value}\n"
    env.write_text(raw, encoding="utf-8")
    preferences = root / ".data" / "preferences.json"
    if not preferences.exists():
        preferences.write_text(
            json.dumps({"proactive": True, "performance": "adaptive", "voice_speed": 1.0}),
            encoding="utf-8",
        )
    print(json.dumps({"ram_gb": round(total, 2), "settings": values, "backup": str(backup)}))


if __name__ == "__main__":
    main()
