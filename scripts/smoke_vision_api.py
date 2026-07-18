from __future__ import annotations

import asyncio
import json

import httpx

from jarvis.config import Settings


async def verify() -> dict[str, object]:
    settings = Settings()
    base_url = f"http://{settings.host}:{settings.port}/api"
    session_id = "vision-api-smoke"
    async with httpx.AsyncClient(timeout=settings.vision_timeout + 30) as client:
        requested = await client.post(
            f"{base_url}/chat",
            json={"session_id": session_id, "message": "describe lo que ves en la pantalla"},
        )
        requested.raise_for_status()
        pending = requested.json().get("action") or {}
        confirmed = await client.post(
            f"{base_url}/chat",
            json={"session_id": session_id, "message": "sí, hazlo"},
        )
        confirmed.raise_for_status()
        completed = confirmed.json().get("action") or {}
        audit_response = await client.get(f"{base_url}/actions/audit", params={"limit": 10})
        audit_response.raise_for_status()
        relevant = [
            entry
            for entry in audit_response.json().get("entries", [])
            if entry.get("session_id") == session_id and entry.get("action") == "screen.describe"
        ]
    return {
        "confirmation_requested": pending.get("status") == "pending"
        and pending.get("requires_confirmation") is True,
        "voice_confirmation_completed": completed.get("status") == "completed",
        "ephemeral_capture": completed.get("details", {}).get("ephemeral_capture") is True,
        "audit_redacted": bool(relevant)
        and all(item.get("message") == "<redacted>" for item in relevant),
    }


def main() -> None:
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
