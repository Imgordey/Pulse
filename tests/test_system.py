from types import SimpleNamespace
from unittest.mock import Mock

from pulse.core import system


def test_collects_system_metrics(monkeypatch):
    monkeypatch.setattr(system.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(system.time, "time", lambda: 10000)
    monkeypatch.setattr(system.psutil, "boot_time", lambda: 1000)
    cpu = Mock(return_value=12.5)
    disk = Mock(return_value=SimpleNamespace(used=30, total=100, percent=30.0))
    monkeypatch.setattr(system.psutil, "cpu_percent", cpu)
    monkeypatch.setattr(system.psutil, "disk_usage", disk)
    monkeypatch.setattr(
        system.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(used=40, total=200, percent=20.0),
    )

    assert system.get_system_stats() == system.SystemStats(
        os="Darwin",
        cpu_percent=12.5,
        memory_used=40,
        memory_total=200,
        memory_percent=20.0,
        disk_used=30,
        disk_total=100,
        disk_percent=30.0,
        uptime=9000,
    )
    cpu.assert_called_once_with(interval=0.5)
    disk.assert_called_once_with("/")
