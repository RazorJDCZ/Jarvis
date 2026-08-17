from __future__ import annotations

import math
import os
import shutil
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    captured_at: float
    cpu_percent: float | None
    memory_percent: float | None
    memory_available_gb: float | None
    disk_percent: float | None
    disk_free_gb: float | None
    battery_percent: float | None = None
    plugged_in: bool | None = None


@dataclass(frozen=True, slots=True)
class MonitorThresholds:
    cpu_percent: float = 90.0
    memory_percent: float = 90.0
    disk_percent: float = 92.0
    sustained_samples: int = 3
    cooldown_seconds: float = 300.0
    recovery_margin_percent: float = 5.0
    recovery_samples: int = 3

    def __post_init__(self) -> None:
        for value in (self.cpu_percent, self.memory_percent, self.disk_percent):
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("Los umbrales deben estar entre 0 y 100")
        if not 1 <= self.sustained_samples <= 100:
            raise ValueError("sustained_samples debe estar entre 1 y 100")
        if not math.isfinite(self.cooldown_seconds) or self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds no puede ser negativo")
        if (
            not math.isfinite(self.recovery_margin_percent)
            or not 0 <= self.recovery_margin_percent <= 50
        ):
            raise ValueError("recovery_margin_percent debe estar entre 0 y 50")
        if not 1 <= self.recovery_samples <= 100:
            raise ValueError("recovery_samples debe estar entre 1 y 100")


@dataclass(frozen=True, slots=True)
class SystemAlert:
    metric: str
    value: float
    threshold: float
    created_at: float
    message: str
    recovered: bool = False


class SystemMetricsProvider(Protocol):
    def collect(self, captured_at: float) -> SystemSnapshot: ...


class LocalSystemMetricsProvider:
    """Collects aggregate metrics only; it never enumerates or manages processes."""

    def __init__(self, disk_path: Path | None = None) -> None:
        candidate = Path(disk_path) if disk_path is not None else Path.cwd()
        self.disk_path = candidate.resolve()

    @staticmethod
    def _percent(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        converted = float(value)
        return round(converted, 1) if math.isfinite(converted) else None

    def collect(self, captured_at: float) -> SystemSnapshot:
        cpu: float | None = None
        memory_percent: float | None = None
        memory_available: float | None = None
        battery_percent: float | None = None
        plugged_in: bool | None = None
        try:
            import psutil  # type: ignore[import-not-found]

            memory = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            cpu = self._percent(psutil.cpu_percent(interval=None))
            memory_percent = self._percent(memory.percent)
            memory_available = round(float(memory.available) / (1024**3), 2)
            if battery is not None:
                battery_percent = self._percent(battery.percent)
                plugged_in = bool(battery.power_plugged)
        except (ImportError, AttributeError, OSError, TypeError, ValueError):
            if hasattr(os, "getloadavg"):
                try:
                    load = os.getloadavg()[0]
                    count = os.cpu_count() or 1
                    cpu = self._percent(min(100.0, (load / count) * 100.0))
                except (OSError, ValueError):
                    pass

        disk_percent: float | None = None
        disk_free: float | None = None
        try:
            usage = shutil.disk_usage(self.disk_path)
            disk_percent = round((usage.used / max(1, usage.total)) * 100.0, 1)
            disk_free = round(usage.free / (1024**3), 2)
        except OSError:
            pass
        return SystemSnapshot(
            captured_at=captured_at,
            cpu_percent=cpu,
            memory_percent=memory_percent,
            memory_available_gb=memory_available,
            disk_percent=disk_percent,
            disk_free_gb=disk_free,
            battery_percent=battery_percent,
            plugged_in=plugged_in,
        )


class SystemMonitor:
    """Maintains bounded history and emits one alert per sustained high-usage episode."""

    def __init__(
        self,
        provider: SystemMetricsProvider | None = None,
        *,
        thresholds: MonitorThresholds | None = None,
        history_size: int = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 1 <= history_size <= 10_000:
            raise ValueError("history_size debe estar entre 1 y 10000")
        self.provider = provider or LocalSystemMetricsProvider()
        self.thresholds = thresholds or MonitorThresholds()
        self._history: deque[SystemSnapshot] = deque(maxlen=history_size)
        self._clock = clock
        self._streaks = {"cpu": 0, "memory": 0, "disk": 0}
        self._recovery_streaks = {"cpu": 0, "memory": 0, "disk": 0}
        self._active_alerts: set[str] = set()
        self._last_alert: dict[str, float] = {}

    @property
    def history(self) -> tuple[SystemSnapshot, ...]:
        return tuple(self._history)

    @property
    def latest(self) -> SystemSnapshot | None:
        return self._history[-1] if self._history else None

    def sample(self) -> tuple[SystemSnapshot, tuple[SystemAlert, ...]]:
        now = self._clock()
        snapshot = self.provider.collect(now)
        self._history.append(snapshot)
        configured = (
            ("cpu", snapshot.cpu_percent, self.thresholds.cpu_percent, "CPU"),
            ("memory", snapshot.memory_percent, self.thresholds.memory_percent, "memoria"),
            ("disk", snapshot.disk_percent, self.thresholds.disk_percent, "disco"),
        )
        alerts: list[SystemAlert] = []
        for metric, value, threshold, label in configured:
            if value is None or not math.isfinite(value):
                self._streaks[metric] = 0
                self._recovery_streaks[metric] = 0
                continue

            numeric_value = float(value)
            if metric in self._active_alerts:
                recovery_threshold = max(
                    0.0,
                    threshold - self.thresholds.recovery_margin_percent,
                )
                recovered = numeric_value <= recovery_threshold
                self._recovery_streaks[metric] = (
                    self._recovery_streaks[metric] + 1 if recovered else 0
                )
                if self._recovery_streaks[metric] < self.thresholds.recovery_samples:
                    continue
                self._active_alerts.remove(metric)
                self._streaks[metric] = 0
                self._recovery_streaks[metric] = 0
                alerts.append(
                    SystemAlert(
                        metric=metric,
                        value=numeric_value,
                        threshold=threshold,
                        created_at=now,
                        message=(
                            f"El uso de {label} volvió a un nivel normal: "
                            f"{round(numeric_value, 1)} por ciento."
                        ),
                        recovered=True,
                    )
                )
                continue

            over_threshold = numeric_value >= threshold
            self._streaks[metric] = self._streaks[metric] + 1 if over_threshold else 0
            if self._streaks[metric] < self.thresholds.sustained_samples:
                continue
            last_alert = self._last_alert.get(metric, float("-inf"))
            if now - last_alert < self.thresholds.cooldown_seconds:
                continue
            self._last_alert[metric] = now
            self._active_alerts.add(metric)
            self._streaks[metric] = self.thresholds.sustained_samples
            alerts.append(
                SystemAlert(
                    metric=metric,
                    value=numeric_value,
                    threshold=threshold,
                    created_at=now,
                    message=(
                        f"El uso de {label} alcanzó {round(numeric_value, 1)} por ciento "
                        f"durante {self.thresholds.sustained_samples} muestras consecutivas."
                    ),
                )
            )
        return snapshot, tuple(alerts)


__all__ = [
    "LocalSystemMetricsProvider",
    "MonitorThresholds",
    "SystemAlert",
    "SystemMetricsProvider",
    "SystemMonitor",
    "SystemSnapshot",
]
