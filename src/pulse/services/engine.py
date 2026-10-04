"""An explicit full scan for future UI consumers, with structured stage results."""

from dataclasses import dataclass
from pathlib import Path

from pulse.cleanup.models import StorageScan
from pulse.cleanup.scanner import scan_storage
from pulse.optimization.engine import Recommendation, recommend_maintenance
from pulse.services.monitor import MonitorSnapshot, collect_snapshot


@dataclass(frozen=True)
class ComputerScan:
    monitor: MonitorSnapshot
    storage: StorageScan
    recommendations: tuple[Recommendation, ...]


def scan_computer(home: Path | None = None, include_processes: bool = True) -> ComputerScan:
    monitor = collect_snapshot(include_processes=include_processes)
    storage = scan_storage(home)
    recommendations = recommend_maintenance(monitor.health, storage.candidates)
    return ComputerScan(monitor, storage, recommendations)
