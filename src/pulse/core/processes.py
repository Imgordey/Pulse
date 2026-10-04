"""Read-only process sampling; no presentation or process control."""

import time
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class ProcessStats:
    pid: int
    name: str
    cpu_percent: float
    memory_rss: int
    user: str | None = None


@dataclass(frozen=True)
class ProcessSnapshot:
    processes: tuple[ProcessStats, ...]
    skipped: int


def get_process_stats(interval: float = 0.5) -> ProcessSnapshot:
    if interval < 0.1:
        raise ValueError("Sampling interval must be at least 0.1 seconds")
    candidates: list[psutil.Process] = []
    skipped = 0
    for process in psutil.process_iter():
        try:
            process.cpu_percent(None)
            candidates.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
            skipped += 1
    time.sleep(interval)
    result: list[ProcessStats] = []
    for process in candidates:
        try:
            if not process.is_running():
                skipped += 1
                continue
            try:
                user = process.username()
            except (psutil.AccessDenied, PermissionError):
                user = None
            result.append(
                ProcessStats(
                    pid=process.pid,
                    name=process.name(),
                    cpu_percent=process.cpu_percent(None),
                    memory_rss=process.memory_info().rss,
                    user=user,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
            skipped += 1
    return ProcessSnapshot(tuple(result), skipped)
