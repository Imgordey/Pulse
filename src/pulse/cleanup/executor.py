"""Explicit, conservative execution of previously reviewed cache plans."""

import os
import stat
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from pulse.cleanup.filesystem import (
    DIRECTORY_FLAGS,
    open_directory,
    valid_relative,
    validate_owned_directory_chain,
)
from pulse.cleanup.journal import Journal, create_journal
from pulse.cleanup.models import (
    CleanupPlan,
    CleanupReport,
    CleanupResult,
    FileIdentity,
    PlannedFile,
    Safety,
)
from pulse.cleanup.planner import MAX_PLAN_AGE_SECONDS, classify_file, identity, root_for_category


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


def _remove_file(
    parent_fd: int, name: str, expected: FileIdentity, path: Path, journal: Journal
) -> CleanupResult:
    """Stage atomically, recheck identity, then unlink only inside a private directory.

    If a racing replacement is moved instead, preserve it rather than deleting it.
    This avoids unlinking a replacement between checking and removing the original.
    """
    staging_name = f".pulse-delete-{uuid.uuid4().hex}"
    recovery = path.parent / staging_name / "payload"
    journal.append(
        "intent", {"path": str(path), "recovery_path": str(recovery), "identity": asdict(expected)}
    )
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
        journal.append(
            "staged",
            {"path": str(path), "recovery_path": str(recovery), "identity": asdict(identity(info))},
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


def _execute_item(
    plan: CleanupPlan,
    item: PlannedFile,
    home: Path,
    dry_run: bool,
    journal: Journal | None,
) -> CleanupResult:
    path = plan.root / item.relative_path
    if not valid_relative(item.relative_path) or item.safety != Safety.safe:
        return CleanupResult(path, "skipped", "Protected or invalid path")
    try:
        validate_owned_directory_chain(home, path.parent)
        with open_directory(plan.root) as root_fd:
            info = os.fstat(root_fd)
            if (info.st_dev, info.st_ino) != (plan.root_device, plan.root_inode):
                return CleanupResult(path, "skipped", "Cache root changed since planning")
        with open_directory(path.parent) as parent_fd:
            info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            safety, reason = classify_file(item.relative_path, info, time.time())
            if identity(info) != item.identity or safety != Safety.safe:
                return CleanupResult(path, "skipped", f"File changed or unsafe: {reason}")
            if dry_run:
                return CleanupResult(path, "would_delete", item.reason)
            if journal is None:
                raise PermissionError("Cleanup requires an audit journal")
            return _remove_file(parent_fd, path.name, item.identity, path, journal)
    except FileNotFoundError:
        return CleanupResult(path, "skipped", "File or directory no longer exists")
    except (OSError, ValueError) as exc:
        return CleanupResult(path, "failed", str(exc))


def _execute_cleanup(
    plan: CleanupPlan,
    *,
    dry_run: bool = True,
    confirmed: bool = False,
    home: Path | None = None,
    journal: Journal | None = None,
) -> CleanupReport:
    """No writes in dry-run. Non-dry execution requires explicit caller confirmation.

    Only regular, old, single-link pip HTTP cache files are eligible. Other cache
    categories, arbitrary paths, incomplete/expired plans, and changed files fail closed.
    """
    expected_home = Path.home() if home is None else home
    now = time.time()
    blocked: str | None = None
    try:
        allowed_root = expected_home / root_for_category(plan.category)
    except ValueError:
        allowed_root = None
    if plan.home != expected_home or plan.root != allowed_root:
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
    audit_error = None
    for index, item in enumerate(plan.files):
        path = plan.root / item.relative_path
        if item.relative_path in seen:
            result = CleanupResult(path, "skipped", "Duplicate plan entry")
        else:
            seen.add(item.relative_path)
            result = _execute_item(plan, item, expected_home, dry_run, journal)
        results.append(result)
        if journal is not None:
            try:
                journal.append("result", asdict(result))
            except OSError as exc:
                audit_error = str(exc)
                results.extend(
                    CleanupResult(
                        plan.root / remaining.relative_path,
                        "skipped",
                        "Audit failed; remaining operations stopped",
                    )
                    for remaining in plan.files[index + 1 :]
                )
                break
    removed = sum(result.bytes_removed for result in results)
    # APFS snapshots/shared extents and concurrent writes prevent attributing free-space deltas.
    return CleanupReport(tuple(results), dry_run, removed, None, audit_error=audit_error)


def execute_cleanup(
    plan: CleanupPlan,
    *,
    dry_run: bool = True,
    confirmed: bool = False,
    home: Path | None = None,
) -> CleanupReport:
    """Persist an audit trail before actual cleanup. Dry-run never writes a journal."""
    if dry_run or not confirmed:
        return _execute_cleanup(plan, dry_run=dry_run, confirmed=confirmed, home=home)
    preview = _execute_cleanup(plan, dry_run=True, home=home)
    if preview.blocked_reason or not any(r.status == "would_delete" for r in preview.results):
        return replace(preview, dry_run=False)
    expected_home = Path.home() if home is None else home
    report = None
    journal_path = None
    try:
        with create_journal(expected_home) as journal:
            journal_path = journal.path
            journal.append(
                "started",
                {"root": str(plan.root), "category": plan.category, "files": len(plan.files)},
            )
            report = _execute_cleanup(
                plan, dry_run=False, confirmed=True, home=home, journal=journal
            )
            report = replace(report, journal_path=journal.path)
            counts: dict[str, int] = {}
            for result in report.results:
                counts[result.status] = counts.get(result.status, 0) + 1
            journal.append(
                "finished",
                {
                    "bytes_removed": report.bytes_removed,
                    "counts": counts,
                    "audit_error": report.audit_error,
                },
            )
        return report
    except OSError as exc:
        if report is not None:
            return replace(report, audit_error=str(exc))
        return CleanupReport(
            tuple(
                CleanupResult(
                    plan.root / item.relative_path,
                    "failed",
                    "Audit journal unavailable; cleanup refused",
                )
                for item in plan.files
            ),
            False,
            0,
            None,
            journal_path=journal_path,
            audit_error=str(exc),
        )
