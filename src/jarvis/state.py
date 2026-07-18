from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket

from jarvis.schemas import JarvisState, StateSnapshot


@dataclass(slots=True)
class StateHub:
    current: StateSnapshot = field(default_factory=StateSnapshot)
    _clients: set[WebSocket] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        await websocket.send_json(self.current.model_dump())

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def set(self, state: JarvisState, detail: str) -> None:
        self.current = StateSnapshot(state=state, detail=detail)
        payload = self.current.model_dump()
        stale: list[WebSocket] = []
        async with self._lock:
            for client in self._clients:
                try:
                    await client.send_json(payload)
                except Exception:
                    stale.append(client)
            for client in stale:
                self._clients.discard(client)
