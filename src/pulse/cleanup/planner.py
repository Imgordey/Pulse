"""Plans for old, recognizable files in explicit cache policies."""

import os
import stat
import time
from pathlib import Path
from threading import Event
from types import MappingProxyType

from pulse.cleanup.filesystem import open_directory, open_relative_directory, valid_relative
from pulse.cleanup.models import CleanupPlan, FileIdentity, PlannedFile, Safety
from pulse.cleanup.policies import POLICIES, cache_policy, recognized_path

PIP_ROOT = Path("Library/Caches/pip/http-v2")
CACHE_ROOTS = MappingProxyType({key: policy.root for key, policy in POLICIES.items()})


def root_for_category(category: str) -> Path:
    try:
        return CACHE_ROOTS[category]
    except KeyError as exc:
        raise ValueError("Unsupported cleanup category") from exc


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


def known_cache_path(relative: Path, category: str = "pip-http") -> bool:
    return recognized_path(relative, category)


def classify_file(
    relative: Path, info: os.stat_result, now: float, category: str = "pip-http"
) -> tuple[Safety, str]:
    if not valid_relative(relative) or not stat.S_ISREG(info.st_mode):
        return Safety.protected, "Not a regular cache file"
    policy = cache_policy(category)
    known = known_cache_path(relative, category)
    if not known:
        return Safety.protected, "Unrecognized cache layout"
    if info.st_nlink != 1 or info.st_uid != os.getuid():
        return Safety.protected, "Shared file or different owner"
    if max(info.st_mtime, info.st_atime) > now - policy.minimum_age_days * 86400:
        return Safety.review, f"Modified or accessed within the last {policy.minimum_age_days} days"
    return Safety.safe, policy.consequence


def create_cleanup_plan(
    home: Path | None = None,
    max_entries: int = 50000,
    *,
    category: str = "pip-http",
    max_seconds: float = 30,
    cancel: Event | None = None,
) -> CleanupPlan:
    """Read-only bounded plan, bound to one home and one allowlisted root."""
    if not 1 <= max_entries <= 50000 or not 0 < max_seconds <= 300:
        raise ValueError("max_entries must be between 1 and 50000")
    home = Path.home() if home is None else home
    root = home / root_for_category(category)
    now = time.time()
    deadline = time.monotonic() + max_seconds
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
                    category,
                )
            pending = [(Path("."), device, inode)]
            while pending and visited < max_entries:
                if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
                    complete = False
                    warnings.append("Planning stopped before completion; no cleanup is allowed")
                    break
                relative_dir, expected_device, expected_inode = pending.pop()
                try:
                    # Reopen from the known root, never through a symlink.
                    with open_relative_directory(root_fd, relative_dir) as directory_fd:
                        current = os.fstat(directory_fd)
                        if (current.st_dev, current.st_ino) != (expected_device, expected_inode):
                            skipped += 1
                            complete = False
                            warnings.append("A directory changed during planning; scan again")
                            continue
                        with os.scandir(directory_fd) as entries:
                            for entry in entries:
                                if (
                                    visited >= max_entries
                                    or time.monotonic() >= deadline
                                    or (cancel is not None and cancel.is_set())
                                ):
                                    complete = False
                                    warnings.append("Planning budget reached or cancelled")
                                    pending.clear()
                                    break
                                visited += 1
                                relative = relative_dir / entry.name
                                try:
                                    info = entry.stat(follow_symlinks=False)
                                    if info.st_dev != device:
                                        skipped += 1
                                        complete = False
                                        continue
                                    if stat.S_ISDIR(info.st_mode):
                                        if len(relative.parts) > 64 or entry.name.startswith(
                                            ".pulse-delete-"
                                        ):
                                            skipped += 1
                                            complete = False
                                            continue
                                        if info.st_uid != os.getuid() or info.st_mode & 0o022:
                                            skipped += 1
                                            complete = False
                                        else:
                                            pending.append((relative, info.st_dev, info.st_ino))
                                        continue
                                    safety, reason = classify_file(relative, info, now, category)
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
    if not complete and not warnings:
        warnings.append(
            "Planning hit a limit or a protected/inaccessible directory; cleanup refused"
        )
    files.sort(key=lambda file: str(file.relative_path))
    return CleanupPlan(
        home, root, device, inode, tuple(files), skipped, complete, now, tuple(warnings), category
    )
