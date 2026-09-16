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
    _send_tasks: set[asyncio.Task] = field(default_factory=set)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        await asyncio.wait_for(websocket.send_json(self.current.model_dump()), timeout=1)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def set(self, state: JarvisState, detail: str) -> None:
        self.current = StateSnapshot(state=state, detail=detail)
        payload = self.current.model_dump()
        # Status is advisory; a sleeping phone must never hold up a command.
        if len(self._send_tasks) >= 16:
            return
        task = asyncio.create_task(self._broadcast(payload))
        self._send_tasks.add(task)
        task.add_done_callback(self._send_tasks.discard)

    async def _broadcast(self, payload: dict) -> None:
        async def send(client):
            try:
                await asyncio.wait_for(client.send_json(payload), timeout=0.5)
            except Exception:
                self._clients.discard(client)

        async with self._lock:
            await asyncio.gather(*(send(client) for client in tuple(self._clients)))

    async def close(self) -> None:
        tasks = tuple(self._send_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
