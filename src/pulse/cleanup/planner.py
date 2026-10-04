"""Only old, recognizable pip HTTP cache files are eligible for execution."""

import os
import re
import stat
import time
from pathlib import Path

from pulse.cleanup.filesystem import open_directory, open_relative_directory, valid_relative
from pulse.cleanup.models import CleanupPlan, FileIdentity, PlannedFile, Safety

PIP_ROOT = Path("Library/Caches/pip/http-v2")
MIN_AGE_SECONDS = 7 * 86400
MAX_PLAN_AGE_SECONDS = 15 * 60


def identity(info: os.stat_result) -> FileIdentity:
    return FileIdentity(
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_uid,
        info.st_nlink,
    )


def known_cache_path(relative: Path) -> bool:
    if not valid_relative(relative):
        return False
    parts = relative.parts
    name = parts[-1].removesuffix(".body")
    return (
        len(parts) == 6
        and re.fullmatch(r"[0-9a-f]{56}", name) is not None
        and tuple(name[:5]) == parts[:5]
    )


def classify_file(relative: Path, info: os.stat_result, now: float) -> tuple[Safety, str]:
    if not valid_relative(relative) or not stat.S_ISREG(info.st_mode):
        return Safety.protected, "Not a regular cache file"
    known = known_cache_path(relative)
    if not known:
        return Safety.protected, "Unrecognized pip HTTP cache layout"
    if info.st_nlink != 1 or info.st_uid != os.getuid():
        return Safety.protected, "Shared file or different owner"
    if max(info.st_mtime, info.st_atime) > now - MIN_AGE_SECONDS:
        return Safety.review, "Modified or accessed within the last seven days"
    return Safety.safe, "Old pip HTTP download cache; pip can download it again"


def create_cleanup_plan(home: Path | None = None, max_entries: int = 50000) -> CleanupPlan:
    """Read-only bounded plan, bound to one home and one allowlisted root."""
    if not 1 <= max_entries <= 50000:
        raise ValueError("max_entries must be between 1 and 50000")
    home = Path.home() if home is None else home
    root = home / PIP_ROOT
    now = time.time()
    files: list[PlannedFile] = []
    skipped = visited = 0
    complete = True
    device = inode = 0
    warnings: list[str] = []
    try:
        with open_directory(root) as root_fd:
            root_info = os.fstat(root_fd)
            device, inode = root_info.st_dev, root_info.st_ino
            if root_info.st_uid != os.getuid() or root_info.st_mode & 0o022:
                return CleanupPlan(
                    home,
                    root,
                    device,
                    inode,
                    (),
                    0,
                    False,
                    now,
                    ("Cache root is shared-writable or owned by another user",),
                )
            pending = [Path(".")]
            while pending and visited < max_entries:
                relative_dir = pending.pop()
                try:
                    # Reopen from the known root, never through a symlink.
                    with open_relative_directory(root_fd, relative_dir) as directory_fd:
                        with os.scandir(directory_fd) as entries:
                            for entry in entries:
                                if visited >= max_entries:
                                    complete = False
                                    break
                                visited += 1
                                relative = relative_dir / entry.name
                                try:
                                    info = entry.stat(follow_symlinks=False)
                                    if stat.S_ISDIR(info.st_mode):
                                        if info.st_uid != os.getuid() or info.st_mode & 0o022:
                                            skipped += 1
                                            complete = False
                                        else:
                                            pending.append(relative)
                                        continue
                                    safety, reason = classify_file(relative, info, now)
                                    if safety == Safety.safe:
                                        files.append(
                                            PlannedFile(relative, identity(info), safety, reason)
                                        )
                                    else:
                                        skipped += 1
                                except OSError:
                                    skipped += 1
                                    complete = False
                except OSError:
                    skipped += 1
                    complete = False
            if pending:
                complete = False
    except OSError as exc:
        complete = False
        warnings.append(f"Cache unavailable: {exc.strerror or type(exc).__name__}")
    files.sort(key=lambda file: str(file.relative_path))
    return CleanupPlan(
        home, root, device, inode, tuple(files), skipped, complete, now, tuple(warnings)
    )
