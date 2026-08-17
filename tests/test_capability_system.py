from __future__ import annotations

from dataclasses import replace

from jarvis.capabilities.system import (
    MonitorThresholds,
    SystemMonitor,
    SystemSnapshot,
)


class SequenceProvider:
    def __init__(self, values: list[tuple[float, float, float]]) -> None:
        self.values = values
        self.index = 0

    def collect(self, captured_at: float) -> SystemSnapshot:
        cpu, memory, disk = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return SystemSnapshot(
            captured_at=captured_at,
            cpu_percent=cpu,
            memory_percent=memory,
            memory_available_gb=4.0,
            disk_percent=disk,
            disk_free_gb=20.0,
        )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_monitor_requires_sustained_samples_and_bounds_history() -> None:
    provider = SequenceProvider([(95, 50, 40), (96, 50, 40), (97, 50, 40)])
    monitor = SystemMonitor(
        provider,
        thresholds=MonitorThresholds(sustained_samples=3, cooldown_seconds=60),
        history_size=2,
    )

    assert monitor.sample()[1] == ()
    assert monitor.sample()[1] == ()
    snapshot, alerts = monitor.sample()

    assert snapshot.cpu_percent == 97
    assert len(alerts) == 1
    assert alerts[0].metric == "cpu"
    assert len(monitor.history) == 2
    assert monitor.latest == snapshot


def test_monitor_latches_alert_until_sustained_recovery() -> None:
    clock = FakeClock()
    provider = SequenceProvider(
        [
            (95, 50, 40),
            (95, 50, 40),
            (95, 50, 40),
            (89, 50, 40),
            (84, 50, 40),
            (84, 50, 40),
            (84, 50, 40),
            (95, 50, 40),
            (95, 50, 40),
        ]
    )
    monitor = SystemMonitor(
        provider,
        thresholds=MonitorThresholds(
            sustained_samples=2,
            cooldown_seconds=100,
            recovery_samples=3,
        ),
        clock=clock,
    )

    assert monitor.sample()[1] == ()
    assert len(monitor.sample()[1]) == 1
    clock.now += 10
    assert monitor.sample()[1] == ()
    clock.now += 200
    assert monitor.sample()[1] == ()
    assert monitor.sample()[1] == ()
    assert monitor.sample()[1] == ()
    recovery = monitor.sample()[1]
    assert len(recovery) == 1
    assert recovery[0].recovered is True
    assert "volvió a un nivel normal" in recovery[0].message
    assert monitor.sample()[1] == ()
    assert len(monitor.sample()[1]) == 1


def test_monitor_does_not_repeat_while_usage_stays_high_past_cooldown() -> None:
    clock = FakeClock()
    provider = SequenceProvider([(95, 50, 40)] * 5)
    monitor = SystemMonitor(
        provider,
        thresholds=MonitorThresholds(sustained_samples=2, cooldown_seconds=10),
        clock=clock,
    )

    assert monitor.sample()[1] == ()
    assert len(monitor.sample()[1]) == 1
    clock.now += 1_000
    assert monitor.sample()[1] == ()
    assert monitor.sample()[1] == ()
    assert monitor.sample()[1] == ()


def test_monitor_can_emit_independent_memory_and_disk_alerts() -> None:
    provider = SequenceProvider([(10, 95, 99)])
    thresholds = replace(
        MonitorThresholds(),
        sustained_samples=1,
        cooldown_seconds=0,
    )
    monitor = SystemMonitor(provider, thresholds=thresholds)

    _, alerts = monitor.sample()

    assert {alert.metric for alert in alerts} == {"memory", "disk"}
