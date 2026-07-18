from __future__ import annotations

import asyncio
import json

import httpx

from jarvis.config import Settings


async def verify() -> dict[str, object]:
    settings = Settings()
    base_url = f"http://{settings.host}:{settings.port}/api"
    session_id = "api-smoke"
    cases = (
        "¿Podrías abrir la calculadora, por favor?",
        'abre el bloc de notas y después escribe "INTEGRACION JARVIS"',
        "describe lo que ves en la pantalla",
        "haz clic en el control Comprar ahora",
    )
    results: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for message in cases:
            response = await client.post(
                f"{base_url}/chat",
                json={"session_id": session_id, "message": message},
            )
            response.raise_for_status()
            payload = response.json()
            action = payload.get("action") or {}
            results.append(
                {
                    "message": message,
                    "provider": payload.get("provider"),
                    "status": action.get("status"),
                    "name": action.get("name"),
                    "confirmation": action.get("requires_confirmation", False),
                    "response": payload.get("response"),
                }
            )
            if action.get("requires_confirmation"):
                decision = await client.post(
                    f"{base_url}/actions/decision",
                    json={
                        "session_id": session_id,
                        "action_id": action["action_id"],
                        "approve": False,
                    },
                )
                decision.raise_for_status()
    return {
        "courtesy_app_opened": results[0]["status"] == "completed",
        "workflow_requested_confirmation": results[1]["name"] == "workflow.run"
        and results[1]["status"] == "pending",
        "vision_requested_confirmation": results[2]["name"] == "screen.describe"
        and results[2]["status"] == "pending",
        "financial_control_blocked": results[3]["status"] == "blocked",
        "cases": results,
    }


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
