from typer.testing import CliRunner

from pulse import cli
from pulse.core.system import SystemStats

runner = CliRunner()


def test_help_exposes_status():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.output


def test_default_invocation():
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0
    assert "PULSE" in result.output


def test_status_renders_metrics(monkeypatch):
    gib = 1024**3
    monkeypatch.setattr(
        cli,
        "get_system_stats",
        lambda: SystemStats(
            os="Darwin",
            cpu_percent=12.5,
            memory_used=8 * gib,
            memory_total=16 * gib,
            memory_percent=50.0,
            disk_used=100 * gib,
            disk_total=500 * gib,
            disk_percent=20.0,
            uptime=90060,
        ),
    )
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    for value in ("Darwin", "12.5%", "8.0 GiB", "50.0%", "Disk (/)", "20.0%", "1d 1h 1m"):
        assert value in result.output


def test_status_reports_collection_failure(monkeypatch):
    def fail():
        raise PermissionError("Access denied")

    monkeypatch.setattr(cli, "get_system_stats", fail)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
    assert "Unable to read system metrics" in result.output
    assert "Access denied" in result.output
