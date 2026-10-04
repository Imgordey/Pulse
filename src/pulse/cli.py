from enum import StrEnum

import psutil
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from pulse.cleanup.scanner import scan_cleanup
from pulse.core.diagnostics import assess_system
from pulse.core.processes import get_process_stats
from pulse.core.system import get_system_stats

app = typer.Typer(
    name="pulse",
    help="System health diagnostics. OBSERVE → UNDERSTAND → FIX.",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Pulse — system health, without the noise."""
    if ctx.invoked_subcommand is None:
        console.print("[bold]PULSE[/bold]")
        console.print("[dim]System health, without the noise.[/dim]")
        console.print("Run [bold]pulse status[/bold] to observe your system.")


def _gib(value: int) -> str:
    return f"{value / (1024**3):.1f} GiB"


def _size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("Unreachable")


def _uptime(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{days}d {hours}h {minutes}m"


@app.command()
def status() -> None:
    """Observe CPU, memory, root disk usage, and uptime."""
    try:
        stats = get_system_stats()
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read system metrics: {exc}", style="red", markup=False)
        raise typer.Exit(code=1) from exc

    table = Table(title="PULSE · System status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("OS", Text(stats.os))
    table.add_row("CPU", f"{stats.cpu_percent:.1f}%")
    table.add_row(
        "Memory",
        f"{_gib(stats.memory_used)} / {_gib(stats.memory_total)} ({stats.memory_percent:.1f}%)",
    )
    table.add_row(
        "Disk (/)",
        f"{_gib(stats.disk_used)} / {_gib(stats.disk_total)} ({stats.disk_percent:.1f}%)",
    )
    table.add_row("Available memory", _gib(stats.memory_available))
    table.add_row("Free disk space", _gib(stats.disk_free))
    table.add_row("Swap", f"{_gib(stats.swap_used)} / {_gib(stats.swap_total)}")
    if stats.battery is None:
        table.add_row("Battery", "Unavailable")
    else:
        power = "connected to power" if stats.battery.plugged_in else "on battery"
        table.add_row("Battery", f"{stats.battery.percent:.0f}% · {power}")
    table.add_row("Uptime", _uptime(stats.uptime))
    console.print(table)


class ProcessSort(StrEnum):
    cpu = "cpu"
    memory = "memory"


@app.command()
def processes(
    sort: ProcessSort = ProcessSort.cpu,
    limit: int = typer.Option(10, min=1, max=100),
) -> None:
    """Show the busiest accessible processes from a 0.5 second sample."""
    try:
        snapshot = get_process_stats()
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read processes: {exc}", style="red", markup=False)
        raise typer.Exit(code=1) from exc
    rows = sorted(
        snapshot.processes,
        key=lambda p: (-(p.cpu_percent if sort == ProcessSort.cpu else p.memory_rss), p.pid),
    )[:limit]
    table = Table(title="PULSE · Processes")
    for column in ("PID", "Name", "CPU", "RAM (RSS)"):
        table.add_column(column)
    for process in rows:
        table.add_row(
            str(process.pid),
            Text(process.name),
            f"{process.cpu_percent:.1f}%",
            _gib(process.memory_rss),
        )
    console.print(table)
    console.print("CPU: 100% equals one logical core. RAM: resident memory, not unique allocation.")
    if not rows:
        console.print("No accessible processes found.")
    if snapshot.skipped:
        console.print(f"Skipped {snapshot.skipped} inaccessible or exited processes.")


@app.command()
def doctor() -> None:
    """Explain resource observations and suggest manual next steps."""
    try:
        stats = get_system_stats()
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read system metrics: {exc}", style="red", markup=False)
        raise typer.Exit(code=1) from exc
    console.print("PULSE · Resource observations")
    findings = assess_system(stats)
    if not findings:
        console.print("No resource thresholds exceeded in this sample.")
    for finding in findings:
        console.print(f"{finding.resource}: {finding.message}", markup=False)
        console.print(f"Next: {finding.suggestion}", markup=False)
    console.print("One sample is not a full health assessment. No changes were made.")


@app.command()
def scan() -> None:
    """Preview known developer caches. Never deletes files."""
    candidates = scan_cleanup()
    table = Table(title="PULSE · Cleanup preview (read-only)")
    for column in ("Cache", "Size estimate", "Coverage", "Path"):
        table.add_column(column)
    for candidate in candidates:
        table.add_row(
            candidate.description,
            _size(candidate.size),
            "Complete" if candidate.complete else "Partial",
            Text(str(candidate.path)),
        )
    console.print(table)
    if not candidates:
        console.print("No known cache directories were accessible. This is not a full disk scan.")
    console.print(
        "Review required. No files were deleted. Sizes are not guaranteed reclaimable space."
    )


if __name__ == "__main__":
    app()
