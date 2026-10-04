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


def test_process_sort_limit_and_literal_name(monkeypatch):
    from pulse.core.processes import ProcessSnapshot, ProcessStats

    monkeypatch.setattr(
        cli,
        "get_process_stats",
        lambda: ProcessSnapshot(
            (
                ProcessStats(1, "[red]literal[/red]", 1, 100),
                ProcessStats(2, "cpu-worker", 80, 10),
            ),
            1,
        ),
    )
    result = runner.invoke(cli.app, ["processes", "--sort", "memory", "--limit", "1"])
    assert result.exit_code == 0
    assert "[red]literal[/red]" in result.output
    assert "cpu-worker" not in result.output
    assert "Skipped 1" in result.output
    result = runner.invoke(cli.app, ["processes", "--sort", "cpu", "--limit", "1"])
    assert result.exit_code == 0
    assert "cpu-worker" in result.output
    assert "literal" not in result.output


def test_process_options_validate_before_sampling(monkeypatch):
    def fail():
        raise AssertionError("Should not sample")

    monkeypatch.setattr(cli, "get_process_stats", fail)
    for args in (["--limit", "0"], ["--sort", "invalid"]):
        assert runner.invoke(cli.app, ["processes", *args]).exit_code == 2


def test_doctor_explains_high_cpu(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_system_stats",
        lambda: SystemStats(
            "Darwin",
            95,
            1,
            10,
            10,
            1,
            10,
            10,
            100,
        ),
    )
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "High CPU" in result.output
    assert "pulse processes --sort cpu" in result.output


def test_process_failure(monkeypatch):
    import psutil

    def fail():
        raise psutil.AccessDenied()

    monkeypatch.setattr(cli, "get_process_stats", fail)
    result = runner.invoke(cli.app, ["processes"])
    assert result.exit_code == 1
    assert "Unable to read processes" in result.output


def test_scan_does_not_delete_and_reports_partial(monkeypatch, tmp_path):
    from pulse.cleanup.scanner import CleanupCandidate

    monkeypatch.setattr(
        cli,
        "scan_cleanup",
        lambda: [
            CleanupCandidate(
                tmp_path,
                "developer",
                1024**3,
                "Python cache",
                "review_required",
                False,
                "Review first",
                False,
                1,
            )
        ],
    )
    result = runner.invoke(cli.app, ["scan"])
    assert result.exit_code == 0
    assert "Python cache" in result.output
    assert "Partial" in result.output
    assert "No files were deleted" in result.output
