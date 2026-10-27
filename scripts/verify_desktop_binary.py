"""Verify the deployed desktop binary without printing private configuration values."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILT_EXE = PROJECT_ROOT / "desktop" / "src-tauri" / "target" / "release" / "jarvis-desktop.exe"
DEPLOYED_EXE = Path.home() / "Desktop" / "Jarvis.exe"
SENSITIVE_NAME_PARTS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "CLIENT_ID", "CREDENTIAL")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_values() -> dict[str, bytes]:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return {}
    values: dict[str, bytes] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        normalized = value.strip().strip('"\'')
        normalized_name = name.strip()
        if len(normalized) >= 8 and any(
            marker in normalized_name.upper() for marker in SENSITIVE_NAME_PARTS
        ):
            values[normalized_name] = normalized.encode("utf-8")
    return values


def main() -> None:
    built = BUILT_EXE.read_bytes()
    deployed = DEPLOYED_EXE.read_bytes()
    embedded_names = [name for name, value in private_values().items() if value in built]
    result = {
        "portable_executable": built.startswith(b"MZ"),
        "desktop_matches_release": digest(BUILT_EXE) == digest(DEPLOYED_EXE),
        "sensitive_values_embedded": bool(embedded_names),
        "embedded_variable_names": embedded_names,
        "sha256": digest(DEPLOYED_EXE),
        "size_bytes": len(deployed),
    }
    print(json.dumps(result))
    if (
        not result["portable_executable"]
        or not result["desktop_matches_release"]
        or result["sensitive_values_embedded"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
