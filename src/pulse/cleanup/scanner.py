"""Bounded read-only inventory of known caches; no general filesystem crawl."""

import os
import stat
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from pulse.cleanup.filesystem import open_directory, open_relative_directory
from pulse.cleanup.models import CleanupCandidate, Safety, ScanProblem, ScanProgress, StorageScan


@dataclass(frozen=True)
class CacheLocation:
    relative_path: str
    category: str
    description: str
    safety: Safety = Safety.review


LOCATIONS = (
    CacheLocation("Library/Caches/pip", "developer", "Python package download cache"),
    CacheLocation("Library/Developer/Xcode/DerivedData", "developer", "Xcode generated build data"),
    CacheLocation("Library/Caches/Homebrew", "developer", "Homebrew downloads"),
    CacheLocation(".npm/_cacache", "developer", "npm package cache"),
    CacheLocation("Library/pnpm/store", "developer", "pnpm package store"),
    CacheLocation("Library/Caches/Yarn", "developer", "Yarn package cache"),
    CacheLocation(".gradle/caches", "developer", "Gradle build caches"),
    CacheLocation(".cargo/registry/cache", "developer", "Cargo download cache"),
    CacheLocation("Library/Caches/go-build", "developer", "Go build cache"),
    CacheLocation("Library/Caches/com.apple.helpd", "application_cache", "macOS help cache"),
    CacheLocation("Library/Caches/com.apple.Safari", "browser_cache", "Safari cache"),
    CacheLocation("Library/Caches/Google/Chrome", "browser_cache", "Chrome cache"),
    CacheLocation("Library/Logs/DiagnosticReports", "diagnostics", "Diagnostic reports"),
    CacheLocation(".Trash", "trash", "Trash contents (manual review only)", Safety.protected),
)


@dataclass(frozen=True)
class Inventory:
    logical: int
    allocated: int
    files: int
    inspected: int
    exclusions: dict[str, int]


def _inventory(
    root_fd: int,
    max_entries: int,
    deadline: float,
    cancel: Event | None,
    progress: Callable[[int, int], None],
) -> Inventory:
    root_info = os.fstat(root_fd)
    pending = [(Path("."), root_info.st_dev, root_info.st_ino)]
    seen: set[tuple[int, int]] = set()
    size = allocated = files = visited = 0
    exclusions: Counter[str] = Counter()

    def stop() -> bool:
        if cancel is not None and cancel.is_set():
            exclusions["cancelled"] += 1
        elif time.monotonic() >= deadline:
            exclusions["time limit"] += 1
        elif visited >= max_entries:
            exclusions["entry limit"] += 1
        else:
            return False
        return True

    while pending:
        if stop():
            break
        relative, expected_device, expected_inode = pending.pop()
        try:
            with open_relative_directory(root_fd, relative) as directory_fd:
                actual = os.fstat(directory_fd)
                if (actual.st_dev, actual.st_ino) != (expected_device, expected_inode):
                    exclusions["changed directory"] += 1
                    continue
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        if stop():
                            pending.clear()
                            break
                        visited += 1
                        if visited % 1000 == 0:
                            progress(visited, size)
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if entry.name.startswith(".pulse-delete-"):
                                exclusions["recovery staging"] += 1
                            elif info.st_dev != root_info.st_dev:
                                exclusions["other volume"] += 1
                            elif stat.S_ISDIR(info.st_mode):
                                child = relative / entry.name
                                if len(child.parts) > 64:
                                    exclusions["depth limit"] += 1
                                else:
                                    pending.append((child, info.st_dev, info.st_ino))
                            elif stat.S_ISREG(info.st_mode):
                                identity = (info.st_dev, info.st_ino)
                                if identity not in seen:
                                    seen.add(identity)
                                    size += info.st_size
                                    allocated += info.st_blocks * 512
                                    files += 1
                            else:
                                exclusions["symbolic link or special file"] += 1
                        except OSError:
                            exclusions["inaccessible entry"] += 1
        except OSError:
            exclusions["inaccessible directory"] += 1
    progress(visited, size)
    return Inventory(size, allocated, files, visited, dict(exclusions))


def _locations(home: Path, deadline: float, cancel: Event | None):
    """Discover a bounded set of additional application caches for inspection only."""
    locations = list(LOCATIONS)
    problems = []
    root = home / "Library/Caches"
    known = {
        Path(item.relative_path).parts[2]
        for item in LOCATIONS
        if item.relative_path.startswith("Library/Caches/")
    }
    try:
        with open_directory(root) as fd, os.scandir(fd) as entries:
            for index, entry in enumerate(entries):
                if index >= 500 or time.monotonic() >= deadline or (cancel and cancel.is_set()):
                    problems.append(ScanProblem(root, "Additional cache discovery stopped early"))
                    break
                if entry.name in known or entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        locations.append(
                            CacheLocation(
                                str(Path("Library/Caches") / entry.name),
                                "application_cache",
                                f"Application cache: {entry.name}",
                            )
                        )
                except OSError:
                    problems.append(ScanProblem(root / entry.name, "Unable to inspect cache entry"))
    except FileNotFoundError:
        pass
    except OSError as exc:
        problems.append(ScanProblem(root, str(exc)))
    return tuple(locations), problems


def scan_storage(
    home: Path | None = None,
    max_entries: int = 50000,
    *,
    max_seconds: float = 30,
    cancel: Event | None = None,
    progress: Callable[[ScanProgress], None] | None = None,
) -> StorageScan:
    """Bounded metadata-only inventory. Inspection does not authorize deletion.

    All locations share a time budget. Each location has its own entry budget;
    overlap/shared APFS extents mean category sizes must not be summed as freeable space.
    """
    if not 1 <= max_entries <= 250000 or not 0 < max_seconds <= 300:
        raise ValueError("Invalid scan budget")
    home = Path.home() if home is None else home
    started = time.monotonic()
    deadline = started + max_seconds
    result: list[CleanupCandidate] = []
    locations, problems = _locations(home, deadline, cancel)
    inspected = logical = 0
    unscanned: tuple[Path, ...] = ()
    for index, location in enumerate(locations):
        root = home / location.relative_path
        if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
            unscanned = tuple(home / item.relative_path for item in locations[index:])
            break

        def report(
            visited: int,
            size: int,
            *,
            current_root=root,
            before_count=inspected,
            before_size=logical,
            location_index=index,
        ) -> None:
            if progress is not None:
                progress(
                    ScanProgress(
                        current_root,
                        before_count + visited,
                        before_size + size,
                        location_index,
                        len(locations),
                    )
                )

        try:
            with open_directory(root) as root_fd:
                inventory = _inventory(root_fd, max_entries, deadline, cancel, report)
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append(ScanProblem(root, exc.strerror or type(exc).__name__))
            continue
        inspected += inventory.inspected
        logical += inventory.logical
        result.append(
            CleanupCandidate(
                path=root,
                category=location.category,
                size=inventory.logical,
                description=location.description,
                risk_level=location.safety.value,
                removable=False,
                reason="Review contents and close related apps; large does not mean disposable.",
                complete=not inventory.exclusions,
                skipped=sum(inventory.exclusions.values()),
                id=location.relative_path,
                safety=location.safety,
                allocated_bytes=inventory.allocated,
                files=inventory.files,
                exclusions=inventory.exclusions,
            )
        )
    cancelled = cancel is not None and cancel.is_set()
    return StorageScan(
        tuple(result),
        tuple(problems),
        not problems and not unscanned and not cancelled and all(item.complete for item in result),
        cancelled,
        unscanned,
        inspected,
        time.monotonic() - started,
    )


def scan_cleanup(home: Path | None = None, max_entries: int = 50000) -> list[CleanupCandidate]:
    """Compatibility API; scan_storage also reports coverage and inaccessible locations."""
    return list(scan_storage(home, max_entries).candidates)
