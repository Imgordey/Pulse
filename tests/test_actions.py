import subprocess
from unittest.mock import Mock

from typer.testing import CliRunner

from pulse.cli import app
from pulse.optimization import actions


def test_unconfirmed_action_has_no_effect(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(actions.subprocess, "run", run)
    result = actions.run_maintenance("quicklook-cache", home=tmp_path)
    assert result.status == "cancelled"
    run.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_fixed_command_timeout_and_private_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(actions.sys, "platform", "darwin")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "reset", ""))
    monkeypatch.setattr(actions.subprocess, "run", run)
    result = actions.run_maintenance("quicklook-cache", confirmed=True, home=tmp_path)
    assert result.status == "completed"
    assert run.call_args.args[0] == ("/usr/bin/qlmanage", "-r", "cache")
    assert run.call_args.kwargs["timeout"] == 30
    assert not run.call_args.kwargs.get("shell")
    assert result.journal_path.stat().st_mode & 0o777 == 0o600


def test_audit_failure_does_not_launch_tool(tmp_path, monkeypatch):
    from pulse.cleanup.journal import Journal

    monkeypatch.setattr(actions.sys, "platform", "darwin")
    monkeypatch.setattr(Journal, "append", Mock(side_effect=OSError("disk full")))
    run = Mock()
    monkeypatch.setattr(actions.subprocess, "run", run)
    result = actions.run_maintenance("quicklook-cache", confirmed=True, home=tmp_path)
    assert result.status == "failed" and result.audit_error
    run.assert_not_called()


def test_timeout_reports_uncertain_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(actions.sys, "platform", "darwin")
    monkeypatch.setattr(
        actions.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired([], 30))
    )
    result = actions.run_maintenance("quicklook-cache", confirmed=True, home=tmp_path)
    assert result.status == "uncertain"


def test_cli_preview_and_cancel_are_read_only(monkeypatch):
    from pulse.presentation import storage

    run = Mock()
    monkeypatch.setattr(storage, "run_maintenance", run)
    runner = CliRunner()
    assert runner.invoke(app, ["maintain", "quicklook-cache", "--dry-run"]).exit_code == 0
    assert runner.invoke(app, ["maintain", "quicklook-cache"], input="n\n").exit_code == 0
    assert runner.invoke(app, ["maintain", "unknown"]).exit_code == 2
    run.assert_not_called()
