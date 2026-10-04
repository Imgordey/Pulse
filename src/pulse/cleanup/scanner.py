"""Bounded, read-only inventory of explicitly known cache directories."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    category: str
    size: int
    description: str
    risk_level: str
    removable: bool
    reason: str
    complete: bool
    skipped: int


@dataclass(frozen=True)
class CacheLocation:
    relative_path: str
    category: str
    description: str


LOCATIONS = (
    CacheLocation("Library/Caches/pip", "developer", "Python package download cache"),
    CacheLocation("Library/Developer/Xcode/DerivedData", "developer", "Xcode generated build data"),
)


def _safe_root(home: Path, relative_path: str) -> Path | None:
    current = home
    try:
        if not stat.S_ISDIR(current.lstat().st_mode):
            return None
        for part in Path(relative_path).parts:
            current = current / part
            if not stat.S_ISDIR(current.lstat().st_mode):
                return None
    except OSError:
        return None
    return current


def scan_cleanup(home: Path | None = None, max_entries: int = 50000) -> list[CleanupCandidate]:
    """Return known caches only; sizes are estimates, not guaranteed reclaimed bytes.

    No symlinks are intentionally traversed. This inventory is not an authorization
    to delete: live applications and filesystem changes require a later safety check.
    """
    if max_entries < 1:
        raise ValueError("max_entries must be positive")
    home = Path.home() if home is None else home
    result: list[CleanupCandidate] = []
    for location in LOCATIONS:
        root = _safe_root(home, location.relative_path)
        if root is None:
            continue
        pending = [root]
        visited: set[tuple[int, int]] = set()
        size = skipped = entries = 0
        complete = True
        while pending and entries < max_entries:
            directory = pending.pop()
            try:
                if not stat.S_ISDIR(directory.lstat().st_mode):
                    skipped += 1
                    complete = False
                    continue
                with os.scandir(directory) as children:
                    for child in children:
                        if entries >= max_entries:
                            complete = False
                            break
                        entries += 1
                        try:
                            info = child.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode):
                                pending.append(Path(child.path))
                            elif stat.S_ISREG(info.st_mode):
                                identity = (info.st_dev, info.st_ino)
                                if identity not in visited:
                                    visited.add(identity)
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
        if pending:
            complete = False
        result.append(
            CleanupCandidate(
                path=root,
                category=location.category,
                size=size,
                description=location.description,
                risk_level="review_required",
                removable=False,
                reason="Rebuildable data; close related tools and review before cleanup.",
                complete=complete,
                skipped=skipped,
            )
        )
    return result
