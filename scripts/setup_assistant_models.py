"""Install the small local wake models. No audio or documents leave this computer."""
from pathlib import Path

import httpx


def main():
    root = Path(__file__).resolve().parents[1] / "models" / "wake"
    root.mkdir(parents=True, exist_ok=True)
    base = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
    for name in ("hey_jarvis_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx"):
        target = root / name
        if target.exists():
            continue
        with httpx.Client(follow_redirects=True, timeout=90) as client:
            response = client.get(base + name)
            response.raise_for_status()
        temporary = target.with_suffix(".download")
        temporary.write_bytes(response.content)
        temporary.replace(target)
        print(f"Installed {name}: {len(response.content)} bytes", flush=True)


if __name__ == "__main__":
    main()
