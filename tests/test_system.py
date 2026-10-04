from types import SimpleNamespace
from unittest.mock import Mock

from pulse.core import system


def test_collects_system_metrics(monkeypatch):
    monkeypatch.setattr(system.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(system.platform, "mac_ver", lambda: ("15.0", (), ""))
    monkeypatch.setattr(system.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(system.psutil, "cpu_count", lambda logical: 8 if logical else 4)
    monkeypatch.setattr(system.psutil, "getloadavg", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(system, "get_network_totals", lambda: None)
    monkeypatch.setattr(system.time, "time", lambda: 10000)
    monkeypatch.setattr(system.psutil, "boot_time", lambda: 1000)
    cpu = Mock(return_value=12.5)
    disk = Mock(return_value=SimpleNamespace(used=30, total=100, percent=30.0, free=70))
    monkeypatch.setattr(system.psutil, "cpu_percent", cpu)
    monkeypatch.setattr(system.psutil, "disk_usage", disk)
    monkeypatch.setattr(
        system.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(used=40, total=200, percent=20.0, available=160),
    )

    monkeypatch.setattr(system.psutil, "swap_memory", lambda: SimpleNamespace(used=10, total=50))
    monkeypatch.setattr(
        system.psutil,
        "sensors_battery",
        lambda: SimpleNamespace(
            percent=80.0,
            power_plugged=False,
            secsleft=3600,
        ),
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
        memory_available=160,
        disk_free=70,
        swap_used=10,
        swap_total=50,
        battery=system.BatteryStats(80.0, False, 3600),
        os_version="15.0",
        architecture="arm64",
        logical_cpus=8,
        physical_cpus=4,
        load_average=(1.0, 2.0, 3.0),
    )
    cpu.assert_called_once_with(interval=0.5)
    disk.assert_called_once_with("/")


def test_battery_permission_error_is_optional(monkeypatch):
    import psutil

    monkeypatch.setattr(
        system.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            used=40,
            total=200,
            percent=20.0,
            available=160,
        ),
    )
    monkeypatch.setattr(
        system.psutil,
        "disk_usage",
        lambda _: SimpleNamespace(
            used=30,
            total=100,
            percent=30.0,
            free=70,
        ),
    )
    monkeypatch.setattr(system.psutil, "swap_memory", lambda: SimpleNamespace(used=0, total=0))
    monkeypatch.setattr(system.psutil, "cpu_percent", lambda **_: 0)
    monkeypatch.setattr(system.psutil, "boot_time", lambda: 100)
    monkeypatch.setattr(system.time, "time", lambda: 90)

    def denied():
        raise psutil.AccessDenied()

    monkeypatch.setattr(system.psutil, "sensors_battery", denied)
    result = system.get_system_stats()
    assert result.battery is None
    assert result.uptime == 0
