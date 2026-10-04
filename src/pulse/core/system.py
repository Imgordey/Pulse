import platform
import time
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class BatteryStats:
    percent: float
    plugged_in: bool
    seconds_left: int | None


@dataclass(frozen=True)
class SystemStats:
    os: str
    cpu_percent: float
    memory_used: int
    memory_total: int
    memory_percent: float
    disk_used: int
    disk_total: int
    disk_percent: float
    uptime: int
    memory_available: int = 0
    disk_free: int = 0
    swap_used: int = 0
    swap_total: int = 0
    battery: BatteryStats | None = None


def get_system_stats() -> SystemStats:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    swap = psutil.swap_memory()
    try:
        power = psutil.sensors_battery()
    except (OSError, psutil.Error):
        power = None
    battery = (
        None
        if power is None
        else BatteryStats(
            percent=power.percent,
            plugged_in=power.power_plugged,
            seconds_left=power.secsleft if power.secsleft >= 0 else None,
        )
    )

    return SystemStats(
        os=platform.system(),
        cpu_percent=psutil.cpu_percent(interval=0.5),
        memory_used=memory.used,
        memory_total=memory.total,
        memory_percent=memory.percent,
        disk_used=disk.used,
        disk_total=disk.total,
        disk_percent=disk.percent,
        uptime=max(0, int(time.time() - psutil.boot_time())),
        memory_available=memory.available,
        disk_free=disk.free,
        swap_used=swap.used,
        swap_total=swap.total,
        battery=battery,
    )
