from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

TokenSink = Callable[[str], Awaitable[None]]
token_sink: ContextVar[TokenSink | None] = ContextVar("token_sink", default=None)
active_timing: ContextVar[dict[str, float] | None] = ContextVar("active_timing", default=None)


@contextmanager
def stage(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timing = active_timing.get()
        if timing is not None:
            timing[name] = round(timing.get(name, 0) + (time.perf_counter() - started) * 1000, 1)


def available_ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().available / 1024**3
    except (ImportError, OSError):
        return 0.0


def gpu_free_mb() -> float | None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=True,
        )
        return min(float(line) for line in result.stdout.splitlines() if line.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def model_keep_alive(settings: Any, configured: str) -> str:
    from jarvis.services.preferences import PreferenceStore

    if PreferenceStore(settings.data_dir / "preferences.json").get().performance == "economy":
        return "0s"
    if not settings.adaptive_resources:
        return configured
    return "3m" if available_ram_gb() >= settings.model_reserve_gb else "0s"


@dataclass
class PerformanceLog:
    records: deque = field(default_factory=lambda: deque(maxlen=200))

    def record(self, session: str, timing: dict[str, float]) -> None:
        self.records.append({"session": session, "at": time.time(), "timings_ms": dict(timing)})

    def recent(self, session: str) -> list[dict]:
        return [item for item in self.records if item["session"] == session][-20:]


async def response_events(operation, log: PerformanceLog, session: str):
    """Bounded per-request stream. Disconnecting cancels inference, never retries actions."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    timing: dict[str, float] = {}
    started = time.perf_counter()

    async def emit(text: str):
        timing.setdefault("first_text", round((time.perf_counter() - started) * 1000, 1))
        await queue.put({"event": "token", "text": text})

    async def run():
        sink_token = token_sink.set(emit)
        time_token = active_timing.set(timing)
        try:
            result = await operation()
            timing["total"] = round((time.perf_counter() - started) * 1000, 1)
            await queue.put({"event": "done", **result.model_dump(), "timings_ms": timing})
        except Exception:
            await queue.put({"event": "error", "detail": "No pude completar la solicitud."})
        finally:
            token_sink.reset(sink_token)
            active_timing.reset(time_token)
            log.record(session, timing)

    task = asyncio.create_task(run())
    try:
        yield json.dumps({"event": "accepted"}) + "\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                yield '{"event":"heartbeat"}\n'
                continue
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["event"] in {"done", "error"}:
                break
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
