from __future__ import annotations

import asyncio
import json

from jarvis.capabilities.connectors import AppaConnector, load_appa_bridge_descriptor
from jarvis.config import Settings


async def main() -> int:
    settings = Settings()
    descriptor_path = settings.appa_bridge_config_path
    if descriptor_path is None:
        raise RuntimeError("No hay descriptor local de Appa configurado.")
    descriptor = load_appa_bridge_descriptor(descriptor_path)
    connector = AppaConnector(descriptor.base_url, descriptor.token, settings.appa_timeout)
    try:
        context = await connector.personal_context()
    finally:
        await connector.close()
    print(
        json.dumps(
            {
                "source": context["source"],
                "counts": context["counts"],
                "task_preview": len(context["tasks"]),
                "project_preview": len(context["projects"]),
                "event_preview": len(context["events"]),
                "inbox_preview": len(context["inbox"]),
                "focus_active": context["focus"] is not None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
