"""Live Luna vision check with a synthetic image; never captures the user's screen."""

from __future__ import annotations

import asyncio
import io
import json

from PIL import Image, ImageDraw

from jarvis.actions.vision import LocalVisionController
from jarvis.config import Settings
from jarvis.providers.codex_app_server import CodexAppServerClient


async def main() -> None:
    settings = Settings()
    codex = CodexAppServerClient(settings)
    controller = LocalVisionController(settings, codex_client=codex)
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 560, 280), outline="navy", width=8)
    draw.text((190, 155), "PRUEBA JARVIS", fill="black")
    content = io.BytesIO()
    image.save(content, format="PNG")
    try:
        result = await controller.analyze_image_bytes(
            content.getvalue(),
            "Describe el texto y la figura visibles.",
            source_label="imagen sintética de validación",
        )
        report = {
            "success": result.success,
            "message": result.message,
            "details": result.details,
            "real_screen_captured": False,
        }
        print(json.dumps(report, ensure_ascii=False))
        if not result.success:
            raise RuntimeError(result.message)
    finally:
        await codex.close()


if __name__ == "__main__":
    asyncio.run(main())
