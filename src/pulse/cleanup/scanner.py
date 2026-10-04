"""Bounded read-only inventory of known caches; no general filesystem crawl."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pulse.cleanup.filesystem import open_directory, open_relative_directory
from pulse.cleanup.models import CleanupCandidate, Safety, ScanProblem, StorageScan


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


def _inventory(root_fd: int, max_entries: int) -> tuple[int, int, bool]:
    root_info = os.fstat(root_fd)
    pending = [(Path("."), root_info.st_dev, root_info.st_ino)]
    seen: set[tuple[int, int]] = set()
    size = skipped = visited = 0
    complete = True
    while pending and visited < max_entries:
        relative, expected_device, expected_inode = pending.pop()
        try:
            with open_relative_directory(root_fd, relative) as directory_fd:
                actual = os.fstat(directory_fd)
                if (actual.st_dev, actual.st_ino) != (expected_device, expected_inode):
                    skipped += 1
                    complete = False
                    continue
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        if visited >= max_entries:
                            complete = False
                            break
                        visited += 1
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if entry.name.startswith(".pulse-delete-"):
                                skipped += 1
                                complete = False
                            elif info.st_dev != root_info.st_dev:
                                skipped += 1
                                complete = False
                            elif stat.S_ISDIR(info.st_mode):
                                pending.append((relative / entry.name, info.st_dev, info.st_ino))
                            elif stat.S_ISREG(info.st_mode):
                                identity = (info.st_dev, info.st_ino)
                                if identity not in seen:
                                    seen.add(identity)
                                    size += info.st_size
                            else:
                                skipped += 1
                                complete = False
                        except OSError:
                            skipped += 1
                            complete = False
        except OSError:
            skipped += 1
            complete = False
    return size, skipped, complete and not pending


def scan_storage(home: Path | None = None, max_entries: int = 50000) -> StorageScan:
    """Estimate known directory sizes; inaccessible roots remain visible as problems.

    Logical lengths are not reclaimable bytes. Unknown data, browser profiles,
    Documents, projects and Downloads are never eligible for engine deletion.
    """
    if not 1 <= max_entries <= 50000:
        raise ValueError("max_entries must be between 1 and 50000")
    home = Path.home() if home is None else home
    result: list[CleanupCandidate] = []
    problems: list[ScanProblem] = []
    for location in LOCATIONS:
        root = home / location.relative_path
        try:
            with open_directory(root) as root_fd:
                size, skipped, complete = _inventory(root_fd, max_entries)
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append(ScanProblem(root, exc.strerror or type(exc).__name__))
            continue
        result.append(
            CleanupCandidate(
                path=root,
                category=location.category,
                size=size,
                description=location.description,
                risk_level=location.safety.value,
                removable=False,
                reason="Review contents and close related apps; large does not mean disposable.",
                complete=complete,
                skipped=skipped,
                id=location.relative_path,
                safety=location.safety,
            )
        )
    return StorageScan(tuple(result), tuple(problems))


def scan_cleanup(home: Path | None = None, max_entries: int = 50000) -> list[CleanupCandidate]:
    """Compatibility API; use scan_storage to also retrieve inaccessible-root problems."""
    return list(scan_storage(home, max_entries).candidates)
