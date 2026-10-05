"""An explicit full scan for future UI consumers, with structured stage results."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import psutil

from pulse.cleanup.models import ScanProgress, StorageScan
from pulse.cleanup.scanner import scan_storage
from pulse.optimization.engine import Recommendation, recommend_maintenance
from pulse.services.monitor import MonitorSnapshot, collect_snapshot


@dataclass(frozen=True)
class ComputerScan:
    monitor: MonitorSnapshot | None
    storage: StorageScan
    recommendations: tuple[Recommendation, ...]
    monitor_error: str | None = None


def scan_computer(
    home: Path | None = None,
    include_processes: bool = True,
    *,
    cancel: Event | None = None,
    progress: Callable[[ScanProgress], None] | None = None,
    max_seconds: float = 30,
    max_entries: int = 50000,
) -> ComputerScan:
    monitor_error = None
    try:
        monitor = collect_snapshot(include_processes=include_processes)
    except (OSError, psutil.Error) as exc:
        monitor = None
        monitor_error = str(exc)
    storage = scan_storage(
        home, cancel=cancel, progress=progress, max_seconds=max_seconds, max_entries=max_entries
    )
    recommendations = recommend_maintenance(monitor.health, storage.candidates) if monitor else ()
    return ComputerScan(monitor, storage, recommendations, monitor_error)
