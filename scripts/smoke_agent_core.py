from __future__ import annotations

import argparse
import asyncio
import json

import httpx

from jarvis.actions.catalog import ActionCatalog
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings

DEFAULT_CASES = (
    "quiero tener el bloc de notas abierto",
    "necesito que organices las ventanas para poder concentrarme",
    "Jarvis, ¿qué es lo que ves en mi monitor número uno?",
    "abre Chrome, busca cursos gratuitos de Python en español y lee los resultados",
)


async def inspect(cases: tuple[str, ...]) -> list[dict[str, object]]:
    settings = Settings()
    catalog = ActionCatalog(settings.data_dir, settings.browser_search_url, settings)
    planner = LocalActionPlanner(settings, catalog.action_names)
    results: list[dict[str, object]] = []
    for request in cases:
        payload = {
            "model": settings.agent_model,
            "messages": [
                {"role": "system", "content": planner._system_prompt()},
                {
                    "role": "user",
                    "content": (
                        "<contexto_no_confiable>[]</contexto_no_confiable>\n"
                        f"<solicitud>{request}</solicitud>"
                    ),
                },
            ],
            "stream": False,
            "think": False,
            "keep_alive": settings.agent_keep_alive,
            "format": planner._schema(),
            "options": {"temperature": 0, "num_ctx": 4_096, "num_predict": 500},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.agent_timeout) as client:
                response = await client.post(f"{settings.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
            decoded = json.loads(response.json()["message"]["content"])
            results.append({"request": request, "decision": decoded})
        except Exception as exc:
            results.append({"request": request, "error": type(exc).__name__})
    await catalog.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Agent Core structured decisions.")
    parser.add_argument("phrases", nargs="*", help="Natural requests to inspect")
    arguments = parser.parse_args()
    cases = tuple(arguments.phrases) or DEFAULT_CASES
    print(json.dumps(asyncio.run(inspect(cases)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
