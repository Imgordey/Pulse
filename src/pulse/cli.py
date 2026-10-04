import json
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated

import psutil
import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from pulse.cleanup.executor import execute_cleanup
from pulse.cleanup.planner import create_cleanup_plan
from pulse.cleanup.scanner import scan_storage
from pulse.core.diagnostics import assess_system
from pulse.core.processes import get_process_stats
from pulse.core.system import get_system_stats
from pulse.health.engine import analyze_health
from pulse.optimization.engine import recommend_maintenance

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
    table.add_row("OS", Text(f"{stats.os} {stats.os_version}".strip()))
    table.add_row("Architecture", stats.architecture or "Unavailable")
    table.add_row(
        "CPU cores", f"{stats.logical_cpus or '?'} logical / {stats.physical_cpus or '?'} physical"
    )
    if stats.load_average is not None:
        table.add_row("Load (1 / 5 / 15 min)", " / ".join(f"{x:.2f}" for x in stats.load_average))
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
    table.add_row(
        "Free disk space", "Unavailable" if stats.disk_free is None else _gib(stats.disk_free)
    )
    table.add_row("Swap", f"{_gib(stats.swap_used)} / {_gib(stats.swap_total)}")
    if stats.battery is None:
        table.add_row("Battery", "Unavailable")
    else:
        power = "connected to power" if stats.battery.plugged_in else "on battery"
        table.add_row("Battery", f"{stats.battery.percent:.0f}% · {power}")
    if stats.network is not None:
        table.add_row(
            "Network totals",
            f"Sent {_size(stats.network.bytes_sent)} / "
            f"received {_size(stats.network.bytes_received)}",
        )
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
    if snapshot.error:
        console.print(snapshot.error, markup=False)
        raise typer.Exit(code=1)


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
def scan(
    details: bool = typer.Option(False, "--details"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Preview known caches and diagnostic reports. Never deletes files."""
    if json_output:
        storage = scan_storage()
        typer.echo(json.dumps(asdict(storage), default=str, ensure_ascii=False))
        return
    with console.status("Scanning known cache locations…"):
        storage = scan_storage()
    table = Table(title="PULSE · Storage preview (read-only)")
    for column in ("Location", "Size estimate", "Safety", "Coverage"):
        table.add_column(column)
    for candidate in storage.candidates:
        table.add_row(
            candidate.description,
            _size(candidate.size),
            candidate.safety.value,
            "Complete" if candidate.complete else "Partial",
        )
    console.print(table)
    if details:
        for candidate in storage.candidates:
            console.print(f"{candidate.category}: {candidate.path}", markup=False)
    if not storage.candidates:
        console.print("No known cache directories were accessible. This is not a full disk scan.")
    for problem in storage.problems:
        console.print(f"Unavailable: {problem.path}: {problem.reason}", markup=False)
    console.print(
        "Review required. No files were deleted. Sizes are not guaranteed reclaimable space."
    )


@app.command()
def health(json_output: bool = typer.Option(False, "--json")) -> None:
    """Explain current resource observations without a storage scan."""
    try:
        report = analyze_health(get_system_stats())
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read system metrics: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(asdict(report), ensure_ascii=False))
        return
    console.print(f"PULSE · {report.status}")
    for issue in report.issues:
        console.print(f"{issue.severity}: {issue.title}", markup=False)
        console.print(issue.description, markup=False)
        console.print(f"Next: {issue.recommendation}", markup=False)
    for limitation in report.limitations:
        console.print(limitation, markup=False)


@app.command()
def optimize() -> None:
    """Recommend legitimate maintenance; never changes settings or stops apps."""
    try:
        report = analyze_health(get_system_stats(), get_process_stats())
    except (OSError, psutil.Error) as exc:
        console.print(f"Unable to read system metrics: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    recommendations = recommend_maintenance(report)
    if not recommendations:
        console.print("No maintenance recommendation from this sample.")
    for item in recommendations:
        console.print(item.title, markup=False)
        console.print(item.action, markup=False)
    console.print("Recommendations only. No changes made.")


class CleanupCategory(StrEnum):
    pip_http = "pip-http"


@app.command()
def clean(
    dry_run: bool = typer.Option(False, "--dry-run"),
    category: Annotated[CleanupCategory | None, typer.Option("--category")] = None,
    details: bool = typer.Option(False, "--details"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Review and explicitly remove old pip HTTP cache files. Defaults to NO."""
    if json_output:
        if not dry_run:
            console.print("--json is supported only with --dry-run.")
            raise typer.Exit(code=2)
        plan = create_cleanup_plan()
        report = execute_cleanup(plan, dry_run=True)
        typer.echo(json.dumps({"plan": asdict(plan), "report": asdict(report)}, default=str))
        if not plan.complete:
            raise typer.Exit(code=1)
        return
    with console.status("Planning eligible cache cleanup…"):
        plan = create_cleanup_plan()
    console.print("PULSE · Cleanup plan")
    console.print(f"Root: {plan.root}", markup=False)
    console.print(
        f"SAFE: {len(plan.files)} old download-cache files · estimate {_size(plan.estimated_bytes)}"
    )
    console.print(
        f"Excluded: {plan.skipped}. Only recognized files unused for at least seven days qualify."
    )
    for warning in plan.warnings:
        console.print(warning, markup=False)
    if details:
        for item in plan.files:
            console.print(f"  {item.relative_path} · {_size(item.identity.size)}", markup=False)
    else:
        console.print("Use --details to display each file in this group.")
    if not plan.complete:
        console.print("Plan incomplete; cleanup refused.")
        raise typer.Exit(code=1)
    if not plan.files:
        console.print("No eligible files. No changes made.")
        return
    if not dry_run:
        if category is None:
            console.print("Select --category pip-http explicitly, or use --dry-run.")
            raise typer.Exit(code=2)
        console.print(
            "Removing these files requires future downloads. Close pip/package installers first."
        )
        if not typer.confirm("Permanently remove only these reviewed cache files?", default=False):
            console.print("Cancelled. No changes made.")
            return
    report = execute_cleanup(plan, dry_run=dry_run, confirmed=not dry_run)
    counts: dict[str, int] = {}
    for result in report.results:
        counts[result.status] = counts.get(result.status, 0) + 1
        if details or result.status in ("failed", "skipped"):
            console.print(f"{result.status}: {result.path} — {result.reason}", markup=False)
        if result.recovery_path is not None:
            console.print(f"Preserved file for recovery: {result.recovery_path}", markup=False)
    console.print("Results: " + ", ".join(f"{state}={count}" for state, count in counts.items()))
    console.print(f"Logical bytes removed: {_size(report.bytes_removed)}")
    console.print(
        "Actual reclaimed disk space is unknown on APFS; no speed improvement is promised."
    )
    if dry_run:
        console.print("Dry run. No filesystem changes made.")
    if any(result.status in ("failed", "skipped") for result in report.results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
