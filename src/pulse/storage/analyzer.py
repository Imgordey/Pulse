"""Bounded metadata-only directory analysis; never follows links or opens file contents."""

import heapq
import os
import stat
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from pulse.cleanup.filesystem import open_directory, open_relative_directory


@dataclass(frozen=True)
class StorageEntry:
    path: Path
    logical_bytes: int
    allocated_bytes: int
    files: int
    directory: bool


@dataclass(frozen=True)
class AnalysisProgress:
    inspected: int
    logical_bytes: int


@dataclass(frozen=True)
class DirectoryAnalysis:
    root: Path
    children: tuple[StorageEntry, ...]
    largest_files: tuple[StorageEntry, ...]
    logical_bytes: int
    allocated_bytes: int
    files: int
    inspected: int
    complete: bool
    cancelled: bool
    exclusions: dict[str, int]
    problems: tuple[str, ...]
    elapsed_seconds: float


def analyze_directory(
    root: Path,
    *,
    max_entries: int = 200_000,
    max_seconds: float = 30,
    largest_limit: int = 100,
    cancel: Event | None = None,
    progress: Callable[[AnalysisProgress], None] | None = None,
) -> DirectoryAnalysis:
    """Count each regular-file inode once; first encountered hard-link path gets attribution.

    Allocated blocks can be shared by APFS clones/snapshots and are NOT reclaimable bytes.
    Coverage is partial whenever links, mount points, errors, or budgets exclude entries.
    Cancellation is cooperative between metadata operations, not during a blocked OS call.
    """
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("Choose an absolute directory without parent traversal")
    if not 1 <= max_entries <= 1_000_000 or not 0 < max_seconds <= 300:
        raise ValueError("Invalid scan budget")
    if not 1 <= largest_limit <= 1000:
        raise ValueError("Invalid largest-file limit")
    started = time.monotonic()
    inspected = files = logical = allocated = 0
    exclusions: Counter[str] = Counter()
    problems: list[str] = []
    children: dict[str, list[int | bool]] = {}
    largest: list[tuple[int, str, StorageEntry]] = []
    seen: set[tuple[int, int]] = set()
    cancelled = False

    def problem(path: Path, error: object) -> None:
        exclusions["unavailable or changed"] += 1
        if len(problems) < 100:
            problems.append(f"{path}: {error}")

    try:
        with open_directory(root) as root_fd:
            root_info = os.fstat(root_fd)
            pending = [(Path("."), root_info.st_dev, root_info.st_ino)]
            while pending:
                relative, device, inode = pending.pop()
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    exclusions["cancelled"] += 1
                    break
                if inspected >= max_entries or time.monotonic() - started >= max_seconds:
                    exclusions["scan budget reached"] += 1
                    break
                try:
                    with open_relative_directory(root_fd, relative) as fd:
                        info = os.fstat(fd)
                        if (info.st_dev, info.st_ino) != (device, inode):
                            raise OSError("Directory changed during scan")
                        with os.scandir(fd) as entries:
                            for entry in entries:
                                if cancel is not None and cancel.is_set():
                                    cancelled = True
                                    exclusions["cancelled"] += 1
                                    pending.clear()
                                    break
                                if (
                                    inspected >= max_entries
                                    or time.monotonic() - started >= max_seconds
                                ):
                                    exclusions["scan budget reached"] += 1
                                    pending.clear()
                                    break
                                inspected += 1
                                path = relative / entry.name
                                bucket = path.parts[0]
                                try:
                                    data = entry.stat(follow_symlinks=False)
                                    if stat.S_ISLNK(data.st_mode):
                                        exclusions["symbolic links"] += 1
                                        continue
                                    if data.st_dev != root_info.st_dev:
                                        exclusions["other volumes"] += 1
                                        continue
                                    if stat.S_ISDIR(data.st_mode):
                                        children.setdefault(bucket, [0, 0, 0, True])
                                        if entry.name == ".Trash" or entry.name.startswith(
                                            ".pulse-delete-"
                                        ):
                                            exclusions["trash or recovery staging"] += 1
                                        elif len(path.parts) > 64:
                                            exclusions["depth limit"] += 1
                                        else:
                                            pending.append((path, data.st_dev, data.st_ino))
                                        continue
                                    if not stat.S_ISREG(data.st_mode):
                                        exclusions["special files"] += 1
                                        continue
                                    identity = (data.st_dev, data.st_ino)
                                    if identity in seen:
                                        exclusions["duplicate hard links"] += 1
                                        continue
                                    seen.add(identity)
                                    blocks = data.st_blocks * 512
                                    size = data.st_size
                                    logical += size
                                    allocated += blocks
                                    files += 1
                                    values = children.setdefault(bucket, [0, 0, 0, False])
                                    values[0] += size
                                    values[1] += blocks
                                    values[2] += 1
                                    item = StorageEntry(root / path, size, blocks, 1, False)
                                    candidate = (size, str(path), item)
                                    if len(largest) < largest_limit:
                                        heapq.heappush(largest, candidate)
                                    elif candidate[:2] > largest[0][:2]:
                                        heapq.heapreplace(largest, candidate)
                                except OSError as exc:
                                    problem(root / path, exc)
                                if progress is not None and inspected % 1000 == 0:
                                    progress(AnalysisProgress(inspected, logical))
                except OSError as exc:
                    problem(root / relative, exc)
    except OSError as exc:
        problem(root, exc)
    if progress is not None:
        progress(AnalysisProgress(inspected, logical))
    return DirectoryAnalysis(
        root,
        tuple(
            sorted(
                (
                    StorageEntry(root / name, int(v[0]), int(v[1]), int(v[2]), bool(v[3]))
                    for name, v in children.items()
                ),
                key=lambda item: (-item.logical_bytes, str(item.path)),
            )
        ),
        tuple(item[2] for item in sorted(largest, reverse=True)),
        logical,
        allocated,
        files,
        inspected,
        not exclusions,
        cancelled,
        dict(exclusions),
        tuple(problems),
        time.monotonic() - started,
    )
