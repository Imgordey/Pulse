from pulse.cleanup.models import StorageScan
from pulse.core.system import SystemStats
from pulse.health.engine import analyze_health
from pulse.services import engine, monitor

BASE = SystemStats("Darwin", 10, 1, 10, 10, 1, 100, 10, 100)


def test_quick_monitor_does_not_collect_processes(monkeypatch) -> None:
    monkeypatch.setattr(monitor, "get_system_stats", lambda: BASE)

    def fail():
        raise AssertionError("Unrequested process collection")

    monkeypatch.setattr(monitor, "get_process_stats", fail)
    snapshot = monitor.collect_snapshot()
    assert snapshot.system == BASE
    assert snapshot.processes is None


def test_full_scan_returns_structured_stages(monkeypatch) -> None:
    snapshot = monitor.MonitorSnapshot(BASE, None, analyze_health(BASE))
    monkeypatch.setattr(engine, "collect_snapshot", lambda **_: snapshot)
    monkeypatch.setattr(engine, "scan_storage", lambda _: StorageScan((), ()))
    result = engine.scan_computer(include_processes=False)
    assert result.monitor == snapshot
    assert result.storage.candidates == ()
    assert result.recommendations == ()
