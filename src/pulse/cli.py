import typer
from rich.console import Console
from rich.table import Table

from pulse.core.system import get_system_stats

app = typer.Typer(
    name="pulse",
    help="System diagnostics for developers. OBSERVE → UNDERSTAND → FIX.",
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
    except OSError as exc:
        console.print(f"Unable to read system metrics: {exc}", style="red", markup=False)
        raise typer.Exit(code=1) from exc

    table = Table(title="PULSE · System status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("OS", stats.os)
    table.add_row("CPU", f"{stats.cpu_percent:.1f}%")
    table.add_row(
        "Memory",
        f"{_gib(stats.memory_used)} / {_gib(stats.memory_total)} ({stats.memory_percent:.1f}%)",
    )
    table.add_row(
        "Disk (/)",
        f"{_gib(stats.disk_used)} / {_gib(stats.disk_total)} ({stats.disk_percent:.1f}%)",
    )
    table.add_row("Uptime", _uptime(stats.uptime))
    console.print(table)


if __name__ == "__main__":
    app()
