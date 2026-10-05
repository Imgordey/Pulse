"""Reviewed regular files in Downloads only. Native Trash adapter; no deletion fallback."""

import os
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from pulse.cleanup.filesystem import (
    DIRECTORY_FLAGS,
    open_directory,
    validate_owned_directory_chain,
)
from pulse.cleanup.journal import Journal, create_journal
from pulse.cleanup.models import FileIdentity
from pulse.cleanup.planner import identity


@dataclass(frozen=True)
class TrashPlan:
    home: Path
    path: Path
    identity: FileIdentity
    parent_device: int
    parent_inode: int
    created_at: float


@dataclass(frozen=True)
class TrashResult:
    path: Path
    status: str
    reason: str
    trash_path: Path | None = None
    recovery_path: Path | None = None
    journal_path: Path | None = None
    audit_error: str | None = None


def validate_download_path(path: Path, home: Path) -> None:
    relative = path.relative_to(home / "Downloads")
    if not relative.parts or any(part.startswith(".") or part == ".." for part in relative.parts):
        raise ValueError("Only visible files inside your Downloads folder are supported")
    if any(part.lower().endswith((".app", ".bundle", ".photoslibrary")) for part in relative.parts):
        raise ValueError("Application and library packages are protected")
    validate_owned_directory_chain(home, path.parent)


def prepare_trash(path: Path, *, home: Path | None = None) -> TrashPlan:
    home = Path.home() if home is None else home
    validate_download_path(path, home)
    with open_directory(path.parent) as fd:
        parent = os.fstat(fd)
        info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Select an owned regular file without symbolic or hard links")
    return TrashPlan(home, path, identity(info), parent.st_dev, parent.st_ino, time.time())


def _move(plan: TrashPlan, move_to_trash: Callable[[Path], Path | None], journal: Journal):
    path = plan.path
    staging_name = f".pulse-delete-{uuid.uuid4().hex}"
    recovery = path.parent / staging_name / path.name
    with open_directory(path.parent) as parent_fd:
        parent = os.fstat(parent_fd)
        if (parent.st_dev, parent.st_ino) != (plan.parent_device, plan.parent_inode):
            raise ValueError("Parent directory changed; review the file again")
        info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if identity(info) != plan.identity or not stat.S_ISREG(info.st_mode):
            raise ValueError("File changed; review it again")
        journal.append(
            "intent",
            {
                "operation": "trash",
                "path": str(path),
                "recovery_path": str(recovery),
                "identity": asdict(plan.identity),
            },
        )
        os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
        staging_fd = os.open(staging_name, DIRECTORY_FLAGS, dir_fd=parent_fd)
        try:
            staged = False
            try:
                os.rename(path.name, path.name, src_dir_fd=parent_fd, dst_dir_fd=staging_fd)
                staged = True
                info = os.stat(path.name, dir_fd=staging_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or replace(identity(info), changed_ns=plan.identity.changed_ns) != plan.identity
                ):
                    return TrashResult(
                        path,
                        "failed",
                        "File changed; preserved for recovery",
                        recovery_path=recovery,
                    )
                journal.append("staged", {"path": str(path), "recovery_path": str(recovery)})
                # Refuse ancestor substitutions before handing an absolute path to the OS adapter.
                with open_directory(recovery.parent) as verified_fd:
                    verified, held = os.fstat(verified_fd), os.fstat(staging_fd)
                    if (verified.st_dev, verified.st_ino) != (held.st_dev, held.st_ino):
                        raise ValueError("Staging directory changed")
                trash_path = move_to_trash(recovery)
                try:
                    os.stat(path.name, dir_fd=staging_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise OSError("Native Trash did not move the staged file")
                staged = False
                return TrashResult(
                    path, "trashed", "Moved to Trash; no space reclaimed yet", trash_path=trash_path
                )
            except (OSError, ValueError) as exc:
                if staged:
                    try:
                        os.stat(path.name, dir_fd=staging_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        staged = False
                        return TrashResult(
                            path,
                            "uncertain",
                            f"{exc}. File left staging; inspect Trash before retrying",
                        )
                return TrashResult(
                    path, "failed", str(exc), recovery_path=recovery if staged else None
                )
            finally:
                if not staged:
                    try:
                        os.rmdir(staging_name, dir_fd=parent_fd)
                    except OSError:
                        pass
        finally:
            os.close(staging_fd)


def execute_trash(
    plan: TrashPlan,
    *,
    move_to_trash: Callable[[Path], Path | None],
    confirmed: bool = False,
    home: Path | None = None,
) -> TrashResult:
    """Revalidate the reviewed identity and persist intent before staging; preserve on error."""
    home = Path.home() if home is None else home
    if not confirmed:
        return TrashResult(plan.path, "cancelled", "Explicit confirmation required")
    result = TrashResult(plan.path, "failed", "No file was moved")
    try:
        if plan.home != home or not 0 <= time.time() - plan.created_at <= 900:
            raise ValueError("Plan expired or belongs to a different home; review again")
        validate_download_path(plan.path, home)
    except (OSError, ValueError) as exc:
        return replace(result, reason=str(exc))
    try:
        with create_journal(home) as journal:
            result = replace(result, journal_path=journal.path)
            try:
                result = replace(_move(plan, move_to_trash, journal), journal_path=journal.path)
            except (OSError, ValueError) as exc:
                result = replace(result, reason=str(exc))
            journal.append("result", asdict(result))
            journal.append(
                "finished",
                {
                    "operation": "trash",
                    "status": result.status,
                    "bytes_removed": 0,
                    "path": str(result.path),
                    "trash_path": result.trash_path,
                    "recovery_path": result.recovery_path,
                },
            )
    except (OSError, ValueError) as exc:
        return replace(result, reason=f"{result.reason}. {exc}", audit_error=str(exc))
    return result
