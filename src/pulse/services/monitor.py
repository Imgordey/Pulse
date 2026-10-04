from dataclasses import dataclass

from pulse.core.processes import ProcessSnapshot, get_process_stats
from pulse.core.system import SystemStats, get_system_stats
from pulse.health.engine import analyze_health
from pulse.health.models import HealthReport


@dataclass(frozen=True)
class MonitorSnapshot:
    system: SystemStats
    processes: ProcessSnapshot | None
    health: HealthReport


def collect_snapshot(include_processes: bool = False) -> MonitorSnapshot:
    system = get_system_stats()
    processes = get_process_stats() if include_processes else None
    return MonitorSnapshot(system, processes, analyze_health(system, processes))
