"""Fixed, non-privileged macOS maintenance actions with confirmation and durable audit."""

import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from pulse.cleanup.journal import create_journal


@dataclass(frozen=True)
class MaintenanceAction:
    id: str
    title: str
    purpose: str
    consequences: str
    arguments: tuple[str, ...]


ACTIONS = (
    MaintenanceAction(
        "quicklook-cache",
        "Rebuild file previews",
        "Use when Finder thumbnails are stale or incorrect.",
        "macOS will regenerate thumbnails as needed. The next previews may appear more slowly. "
        "Your documents are kept. This does not increase available RAM or promise a speed boost.",
        ("/usr/bin/qlmanage", "-r", "cache"),
    ),
)


@dataclass(frozen=True)
class MaintenanceResult:
    action: str
    status: str
    message: str
    returncode: int | None = None
    journal_path: Path | None = None
    audit_error: str | None = None


def run_maintenance(
    action_id: str, *, confirmed: bool = False, home: Path | None = None
) -> MaintenanceResult:
    action = next((item for item in ACTIONS if item.id == action_id), None)
    if action is None:
        raise ValueError("Unknown maintenance action")
    if not confirmed:
        return MaintenanceResult(action.id, "cancelled", "Explicit confirmation is required")
    if sys.platform != "darwin":
        return MaintenanceResult(action.id, "unavailable", "This action requires macOS")
    result = MaintenanceResult(action.id, "failed", "Action was not started")
    try:
        with create_journal(Path.home() if home is None else home) as journal:
            journal.append("maintenance_intent", {"action": action.id})
            try:
                completed = subprocess.run(
                    action.arguments,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=30,
                    check=False,
                    cwd="/",
                    stdin=subprocess.DEVNULL,
                    env=dict(os.environ, PATH="/usr/bin:/bin", LANG="en_US.UTF-8"),
                )
                message = (completed.stdout + completed.stderr)[-8192:].strip()
                result = MaintenanceResult(
                    action.id,
                    "completed" if completed.returncode == 0 else "failed",
                    message or f"Tool exited with code {completed.returncode}",
                    completed.returncode,
                    journal.path,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                result = MaintenanceResult(
                    action.id,
                    "uncertain" if isinstance(exc, subprocess.TimeoutExpired) else "failed",
                    f"{exc}. Refresh and check Finder before retrying.",
                    journal_path=journal.path,
                )
            journal.append(
                "finished",
                {
                    "action": action.id,
                    "status": result.status,
                    "output": result.message,
                    "bytes_removed": 0,
                },
            )
    except (OSError, ValueError) as exc:
        return replace(result, audit_error=str(exc))
    return result
