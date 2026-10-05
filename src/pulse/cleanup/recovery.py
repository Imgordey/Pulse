"""Explicit recovery of files preserved after a failed cleanup, without overwrite."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from pulse.cleanup.filesystem import open_directory, validate_owned_directory_chain
from pulse.cleanup.journal import create_journal
from pulse.cleanup.models import FileIdentity
from pulse.cleanup.planner import CACHE_ROOTS, identity, known_cache_path


@dataclass(frozen=True)
class RecoveryPlan:
    home: Path
    source: Path
    destination: Path
    identity: FileIdentity


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    reason: str
    source: Path
    destination: Path
    journal_path: Path | None = None
    audit_error: str | None = None


def _validate_scope(source: Path, destination: Path, home: Path) -> None:
    relative = None
    for root in CACHE_ROOTS.values():
        try:
            relative = destination.relative_to(home / root)
            break
        except ValueError:
            continue
    if relative is None or not known_cache_path(relative):
        raise ValueError("Recovery destination is outside the known cache layout")
    if (
        source.name != "payload"
        or source.parent.parent != destination.parent
        or not re.fullmatch(r"\.pulse-delete-[0-9a-f]{32}", source.parent.name)
    ):
        raise ValueError("Source must be the matching private staging payload")
    validate_owned_directory_chain(home, source.parent)


def prepare_recovery(source: Path, destination: Path, home: Path | None = None) -> RecoveryPlan:
    home = Path.home() if home is None else home
    _validate_scope(source, destination, home)
    with open_directory(source.parent) as source_fd:
        info = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Only owned, regular, single-link recovery files are supported")
    return RecoveryPlan(home, source, destination, identity(info))


def recover_file(
    plan: RecoveryPlan,
    *,
    dry_run: bool = True,
    confirmed: bool = False,
    home: Path | None = None,
) -> RecoveryResult:
    """Restore with an exclusive hardlink; an existing destination is never overwritten."""
    home = Path.home() if home is None else home
    journal_path = None
    restored = False
    try:
        if plan.home != home:
            raise ValueError("Recovery home does not match the current user")
        _validate_scope(plan.source, plan.destination, home)
        with open_directory(plan.source.parent) as source_fd:
            with open_directory(plan.destination.parent) as destination_fd:
                info = os.stat("payload", dir_fd=source_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise ValueError("Recovery file is not an owned, regular, single-link file")
                if identity(info) != plan.identity:
                    raise ValueError("Recovery file changed; review it again")
                try:
                    os.stat(plan.destination.name, dir_fd=destination_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError("Destination exists; recovery refuses to overwrite it")
                if dry_run:
                    return RecoveryResult(
                        "would_restore", "Dry run; no changes", plan.source, plan.destination
                    )
                if not confirmed:
                    return RecoveryResult(
                        "skipped", "Explicit confirmation required", plan.source, plan.destination
                    )
                with create_journal(home) as journal:
                    journal_path = journal.path
                    journal.append(
                        "restore-intent",
                        {"source": str(plan.source), "destination": str(plan.destination)},
                    )
                    os.link(
                        "payload",
                        plan.destination.name,
                        src_dir_fd=source_fd,
                        dst_dir_fd=destination_fd,
                        follow_symlinks=False,
                    )
                    linked = os.stat(
                        plan.destination.name, dir_fd=destination_fd, follow_symlinks=False
                    )
                    if (linked.st_dev, linked.st_ino) != (
                        plan.identity.device,
                        plan.identity.inode,
                    ):
                        raise ValueError(
                            "Destination changed during recovery; preserved both paths"
                        )
                    journal.append(
                        "restore-linked",
                        {"source": str(plan.source), "destination": str(plan.destination)},
                    )
                    os.unlink("payload", dir_fd=source_fd)
                    restored = True
                    try:
                        os.rmdir(plan.source.parent.name, dir_fd=destination_fd)
                    except OSError:
                        pass
                    journal.append(
                        "restored",
                        {"source": str(plan.source), "destination": str(plan.destination)},
                    )
                return RecoveryResult(
                    "restored",
                    "Cache file restored without overwrite",
                    plan.source,
                    plan.destination,
                    journal_path,
                )
    except (OSError, ValueError, NotImplementedError) as exc:
        if restored:
            return RecoveryResult(
                "restored",
                "Restored, but final audit write failed",
                plan.source,
                plan.destination,
                journal_path,
                str(exc),
            )
        return RecoveryResult("failed", str(exc), plan.source, plan.destination, journal_path)
