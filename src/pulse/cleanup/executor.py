"""Explicit, conservative execution of previously reviewed cache plans."""

import os
import stat
import time
import uuid
from pathlib import Path

from pulse.cleanup.filesystem import DIRECTORY_FLAGS, open_directory, valid_relative
from pulse.cleanup.models import CleanupPlan, CleanupReport, CleanupResult, FileIdentity, Safety
from pulse.cleanup.planner import MAX_PLAN_AGE_SECONDS, PIP_ROOT, classify_file, identity


def _same_content(before: FileIdentity, after: FileIdentity) -> bool:
    # A rename can alter ctime even though the object itself is unchanged.
    return (
        before.device,
        before.inode,
        before.size,
        before.modified_ns,
        before.owner,
        before.links,
    ) == (
        after.device,
        after.inode,
        after.size,
        after.modified_ns,
        after.owner,
        after.links,
    )


def _validate_directory_chain(home: Path, parent: Path) -> None:
    relative = parent.relative_to(home)
    current = home
    for component in (None, *relative.parts):
        if component is not None:
            current /= component
        with open_directory(current) as fd:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise PermissionError(
                    "Cache directories must be owned by you and not shared-writable"
                )


def _remove_file(parent_fd: int, name: str, expected: FileIdentity, path: Path) -> CleanupResult:
    """Stage atomically, recheck identity, then unlink only inside a private directory.

    If a racing replacement is moved instead, preserve it rather than deleting it.
    This avoids unlinking a replacement between checking and removing the original.
    """
    staging_name = f".pulse-delete-{uuid.uuid4().hex}"
    os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
    staging_fd = os.open(staging_name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    staged = False
    try:
        os.rename(name, "payload", src_dir_fd=parent_fd, dst_dir_fd=staging_fd)
        staged = True
        info = os.stat("payload", dir_fd=staging_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or not _same_content(expected, identity(info)):
            return CleanupResult(
                path,
                "failed",
                "File changed during execution; preserved for recovery",
                recovery_path=path.parent / staging_name / "payload",
            )
        os.unlink("payload", dir_fd=staging_fd)
        staged = False
        return CleanupResult(path, "deleted", "Verified cache file removed", expected.size)
    except OSError as exc:
        return CleanupResult(
            path,
            "failed",
            str(exc),
            recovery_path=path.parent / staging_name / "payload" if staged else None,
        )
    finally:
        os.close(staging_fd)
        if not staged:
            try:
                os.rmdir(staging_name, dir_fd=parent_fd)
            except OSError:
                pass


def execute_cleanup(
    plan: CleanupPlan,
    *,
    dry_run: bool = True,
    confirmed: bool = False,
    home: Path | None = None,
) -> CleanupReport:
    """No writes in dry-run. Non-dry execution requires explicit caller confirmation.

    Only regular, old, single-link pip HTTP cache files are eligible. Other cache
    categories, arbitrary paths, incomplete/expired plans, and changed files fail closed.
    """
    expected_home = Path.home() if home is None else home
    now = time.time()
    blocked: str | None = None
    if plan.home != expected_home or plan.root != expected_home / PIP_ROOT:
        blocked = "Protected path: plan is outside the allowlisted cache root"
    elif not plan.complete:
        blocked = "Incomplete plan; scan again before cleanup"
    elif not 0 <= now - plan.created_at <= MAX_PLAN_AGE_SECONDS:
        blocked = "Plan expired; scan again"
    elif not dry_run and not confirmed:
        blocked = "Explicit confirmation is required"
    if blocked:
        return CleanupReport(
            tuple(
                CleanupResult(plan.root / item.relative_path, "skipped", blocked)
                for item in plan.files
            ),
            dry_run,
            0,
            None,
            blocked,
        )
    results: list[CleanupResult] = []
    seen: set[Path] = set()
    for item in plan.files:
        path = plan.root / item.relative_path
        if not valid_relative(item.relative_path) or item.safety != Safety.safe:
            results.append(CleanupResult(path, "skipped", "Protected or invalid path"))
            continue
        if item.relative_path in seen:
            results.append(CleanupResult(path, "skipped", "Duplicate plan entry"))
            continue
        seen.add(item.relative_path)
        try:
            _validate_directory_chain(expected_home, path.parent)
            with open_directory(plan.root) as root_fd:
                info = os.fstat(root_fd)
                if (info.st_dev, info.st_ino) != (plan.root_device, plan.root_inode):
                    results.append(
                        CleanupResult(path, "skipped", "Cache root changed since planning")
                    )
                    continue
            with open_directory(path.parent) as parent_fd:
                info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                safety, reason = classify_file(item.relative_path, info, now)
                if identity(info) != item.identity or safety != Safety.safe:
                    results.append(
                        CleanupResult(path, "skipped", f"File changed or unsafe: {reason}")
                    )
                elif dry_run:
                    results.append(CleanupResult(path, "would_delete", item.reason))
                else:
                    results.append(_remove_file(parent_fd, path.name, item.identity, path))
        except FileNotFoundError:
            results.append(CleanupResult(path, "skipped", "File or directory no longer exists"))
        except (OSError, ValueError) as exc:
            results.append(CleanupResult(path, "failed", str(exc)))
    removed = sum(result.bytes_removed for result in results)
    # APFS snapshots/shared extents and concurrent writes prevent attributing free-space deltas.
    return CleanupReport(tuple(results), dry_run, removed, None)
