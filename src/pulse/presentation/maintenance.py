import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from pulse.cleanup.journal import read_history
from pulse.cleanup.recovery import prepare_recovery, recover_file

console = Console()


def history_command(
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show local cleanup history and potential preserved-file recovery paths."""
    try:
        records = read_history(limit=limit)
    except (OSError, ValueError) as exc:
        console.print(f"Unable to read history: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(records, default=str))
        return
    if not records:
        console.print("No cleanup history. Dry runs do not create journals.")
    for record in records:
        console.print(f"Journal: {record['journal']}", markup=False)
        if "error" in record:
            console.print(f"History error: {record['error']}", markup=False)
        else:
            event = record.get("last_event")
            console.print(json.dumps(event, default=str), markup=False)
        for item in record.get("potential_recoveries", []):
            console.print(f"Potential preserved file: {item['recovery_path']}", markup=False)
            console.print(f"Original path: {item['path']}", markup=False)
    console.print("History is an audit record; verify preserved files before recovery.")


def recover_command(
    source: Path,
    destination: Annotated[Path, typer.Option("--to")],
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Restore a supported preserved file or trashed download without overwrite."""
    try:
        plan = prepare_recovery(source, destination)
    except (OSError, ValueError) as exc:
        console.print(f"Recovery refused: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    console.print(f"Preserved file: {source}", markup=False)
    console.print(f"Restore to: {destination}", markup=False)
    if not dry_run and not typer.confirm(
        "Restore this file without overwriting existing data?", default=False
    ):
        console.print("Cancelled. No changes made.")
        return
    result = recover_file(plan, dry_run=dry_run, confirmed=not dry_run)
    console.print(f"{result.status}: {result.reason}", markup=False)
    if result.journal_path is not None:
        console.print(f"Journal: {result.journal_path}", markup=False)
    if result.audit_error:
        console.print(f"Audit error: {result.audit_error}", markup=False)
    if result.audit_error or result.status in ("failed", "skipped"):
        raise typer.Exit(code=1)
