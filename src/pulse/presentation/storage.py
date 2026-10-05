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

from pulse.core.volumes import get_volumes
from pulse.optimization.actions import ACTIONS, run_maintenance
from pulse.storage.analyzer import analyze_directory

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
        for name in ("Path", "Logical bytes", "Allocated bytes"):
            table.add_column(name)
        for entry in result.largest_files:
            table.add_row(
                Text(str(entry.path)), str(entry.logical_bytes), str(entry.allocated_bytes)
            )
        console.print(table)
        console.print(
            f"{'Complete' if result.complete else 'Partial'} · {result.files} files · "
            f"{result.logical_bytes} logical bytes · {result.allocated_bytes} allocated bytes"
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
    for name in ("Mount point", "Filesystem", "Capacity bytes", "Available bytes"):
        table.add_column(name)
    for volume in volumes:
        table.add_row(
            Text(volume.mountpoint),
            Text(volume.filesystem),
            str(volume.total) if volume.total is not None else "Unavailable",
            str(volume.free) if volume.free is not None else "Unavailable",
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
