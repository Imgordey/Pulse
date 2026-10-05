"""CLI presentation for disk analysis and narrow maintenance actions."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import psutil
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from pulse.cleanup.policies import POLICIES
from pulse.core.drives import get_drives
from pulse.core.volumes import get_volumes
from pulse.optimization.actions import ACTIONS, run_maintenance
from pulse.presentation.formatting import format_size
from pulse.storage.analyzer import analyze_directory
from pulse.storage.trash import execute_trash, prepare_trash

console = Console()


def analyze_command(
    path: Annotated[Path, typer.Argument()] = Path("~"),
    json_output: bool = typer.Option(False, "--json"),
    limit: int = typer.Option(20, min=1, max=100),
    max_entries: int = typer.Option(200_000, min=1, max=1_000_000),
    seconds: float = typer.Option(30, min=0.1, max=300),
) -> None:
    """Inspect a folder and its largest files; bounded, metadata-only and read-only."""
    result = analyze_directory(
        path.expanduser().absolute(),
        max_entries=max_entries,
        max_seconds=seconds,
        largest_limit=limit,
    )
    if json_output:
        typer.echo(json.dumps(asdict(result), default=str, ensure_ascii=False))
    else:
        table = Table(title="PULSE · Largest files (read-only)")
        for name in ("Path", "Logical size", "Allocated blocks"):
            table.add_column(name)
        for entry in result.largest_files:
            table.add_row(
                Text(str(entry.path)),
                format_size(entry.logical_bytes),
                format_size(entry.allocated_bytes),
            )
        console.print(table)
        console.print(
            f"{'Complete' if result.complete else 'Partial'} · {result.files} files · "
            f"{format_size(result.logical_bytes)} logical · "
            f"{format_size(result.allocated_bytes)} allocated"
        )
        for reason, count in result.exclusions.items():
            console.print(f"Excluded: {count} {reason}", markup=False)
        for problem in result.problems:
            console.print(problem, markup=False)
        console.print("Metadata only. APFS shared blocks are not reclaimable-space estimates.")
    if result.problems and result.inspected == 0:
        raise typer.Exit(code=1)


def volumes_command(json_output: bool = typer.Option(False, "--json")) -> None:
    """Read accessible mounted-volume capacity without summing APFS shared space."""
    try:
        volumes = get_volumes()
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read volumes: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps([asdict(item) for item in volumes], ensure_ascii=False))
        return
    table = Table(title="PULSE · Mounted volumes")
    for name in ("Mount point", "Filesystem", "Capacity", "Available"):
        table.add_column(name)
    for volume in volumes:
        table.add_row(
            Text(volume.mountpoint),
            Text(volume.filesystem),
            format_size(volume.total) if volume.total is not None else "Unavailable",
            format_size(volume.free) if volume.free is not None else "Unavailable",
        )
    console.print(table)
    console.print("APFS volumes share container space. Do not add their free space or capacities.")
    console.print("SMART condition is not measured.")


def maintain_command(
    action: str = typer.Argument("list"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """List specific maintenance actions or review one. Confirmation defaults to NO."""
    if action == "list":
        for item in ACTIONS:
            console.print(f"{item.id}: {item.title}\n{item.purpose}", markup=False)
        return
    selected = next((item for item in ACTIONS if item.id == action), None)
    if selected is None:
        console.print("Unknown action. Run pulse maintain to list supported actions.")
        raise typer.Exit(code=2)
    console.print(f"{selected.title}\n{selected.purpose}\n{selected.consequences}", markup=False)
    if dry_run:
        console.print("Preview only. No action or journal created.")
        return
    if not typer.confirm("Run this specific maintenance action?", default=False):
        console.print("Cancelled. No changes made.")
        return
    result = run_maintenance(action, confirmed=True)
    console.print(f"{result.status}: {result.message}", markup=False)
    if result.audit_error:
        console.print(f"Audit error: {result.audit_error}", markup=False)
    if result.status != "completed" or result.audit_error:
        raise typer.Exit(code=1)


def drives_command(json_output: bool = typer.Option(False, "--json")) -> None:
    """Read physical disk models, connections, capacity and SMART reported by macOS."""
    snapshot = get_drives()
    if json_output:
        typer.echo(json.dumps(asdict(snapshot), ensure_ascii=False))
    else:
        table = Table(title="PULSE · Physical drives")
        for name in ("Device", "Model", "Connection", "Type", "Capacity", "SMART"):
            table.add_column(name)
        for drive in snapshot.drives:
            table.add_row(
                Text(drive.identifier),
                Text(drive.model or "Unavailable"),
                Text(drive.protocol or "Unavailable"),
                "SSD"
                if drive.solid_state
                else "Not reported as SSD"
                if drive.solid_state is False
                else "Unknown",
                format_size(drive.total_bytes) if drive.total_bytes is not None else "Unavailable",
                Text(drive.smart_status or "Unavailable"),
            )
        console.print(table)
        for problem in snapshot.problems:
            console.print(problem, markup=False)
        console.print(
            "SMART is the status reported by macOS, not a full drive test. "
            "Raw device-specific attributes in JSON are not normalized or a health score."
        )
    if not snapshot.complete:
        raise typer.Exit(code=1)


def categories_command() -> None:
    """List exactly supported cleanup categories and their consequences."""
    for policy in POLICIES.values():
        console.print(
            f"{policy.id} · {policy.title} · minimum {policy.minimum_age_days} days\n"
            f"~/{policy.root}\n{policy.consequence}\n",
            markup=False,
        )


def trash_command(
    path: Path,
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Review one personal file for native macOS Trash. Never permanently deletes it."""
    if json_output and not dry_run:
        raise typer.BadParameter("--json requires --dry-run")
    try:
        plan = prepare_trash(path.expanduser().absolute())
    except (OSError, ValueError) as exc:
        console.print(f"File is protected or unavailable: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(asdict(plan), default=str))
        return
    console.print(
        f"Selected file: {plan.path}\nSize: {format_size(plan.identity.size)}", markup=False
    )
    console.print(
        "Close apps using this file. Synced files may also move on other devices. "
        "Trash still occupies space. Restore via Pulse History or move it manually; "
        "Finder Put Back may point to private staging."
    )
    if dry_run:
        console.print("Preview only. No files changed.")
        return
    if not typer.confirm("Move only this file to Trash?", default=False):
        console.print("Cancelled. No files changed.")
        return
    try:
        from pulse.desktop.platform import move_to_trash
    except ModuleNotFoundError as exc:
        console.print("Native Trash requires the desktop extra: pip install -e '.[desktop]'")
        raise typer.Exit(code=1) from exc
    result = execute_trash(plan, move_to_trash=move_to_trash, confirmed=True)
    console.print(f"{result.status}: {result.reason}", markup=False)
    if result.trash_path:
        console.print(f"Trash location: {result.trash_path}", markup=False)
    if result.recovery_path:
        console.print(f"Preserved for recovery: {result.recovery_path}", markup=False)
    if result.audit_error:
        console.print(f"Audit error: {result.audit_error}", markup=False)
    if result.status != "trashed" or result.audit_error:
        raise typer.Exit(code=1)
