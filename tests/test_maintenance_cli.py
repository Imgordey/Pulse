from pathlib import Path

from typer.testing import CliRunner

from pulse.cleanup.recovery import prepare_recovery, recover_file
from pulse.cli import app
from pulse.presentation import maintenance

runner = CliRunner()


def test_history_json_and_missing_history(monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "read_history", lambda **_: ())
    assert runner.invoke(app, ["history", "--json"]).output.strip() == "[]"
    assert "No cleanup history" in runner.invoke(app, ["history"]).output


def test_recovery_cli_defaults_to_no(preserved_file, monkeypatch) -> None:
    home, source, destination = preserved_file
    monkeypatch.setattr(
        maintenance, "prepare_recovery", lambda src, dst: prepare_recovery(src, dst, home)
    )
    result = runner.invoke(app, ["recover", str(source), "--to", str(destination)], input="\n")
    assert result.exit_code == 0
    assert "Cancelled" in result.output
    assert source.exists()


def test_recovery_cli_dry_run(preserved_file, monkeypatch) -> None:
    home, source, destination = preserved_file
    monkeypatch.setattr(
        maintenance, "prepare_recovery", lambda src, dst: prepare_recovery(src, dst, home)
    )
    monkeypatch.setattr(
        maintenance, "recover_file", lambda plan, **kwargs: recover_file(plan, home=home, **kwargs)
    )
    result = runner.invoke(app, ["recover", str(source), "--to", str(destination), "--dry-run"])
    assert result.exit_code == 0
    assert "would_restore" in result.output
    assert source.exists()


def test_arbitrary_destination_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["recover", str(tmp_path / "source"), "--to", str(tmp_path / "Documents")]
    )
    assert result.exit_code == 1
    assert "Recovery refused" in result.output
