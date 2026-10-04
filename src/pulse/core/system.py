import platform
import time
from dataclasses import dataclass

import psutil


@dataclass
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


def get_system_stats() -> SystemStats:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return SystemStats(
        os=platform.system(),
        cpu_percent=psutil.cpu_percent(interval=0.5),
        memory_used=memory.used,
        memory_total=memory.total,
        memory_percent=memory.percent,
        disk_used=disk.used,
        disk_total=disk.total,
        disk_percent=disk.percent,
        uptime=int(time.time() - psutil.boot_time()),
    )
