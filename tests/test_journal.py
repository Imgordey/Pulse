import json
from pathlib import Path
from unittest.mock import Mock

from pulse.cleanup import executor, journal
from pulse.cleanup.planner import create_cleanup_plan


def test_journal_records_before_delete(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    report = executor.execute_cleanup(
        create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
    )
    assert report.journal_path is not None
    events = [json.loads(line)["event"] for line in report.journal_path.read_text().splitlines()]
    assert events == ["started", "intent", "staged", "result", "finished"]
    assert report.journal_path.stat().st_mode & 0o777 == 0o600
    assert not file.exists()
    history = journal.read_history(home)
    assert history[0]["potential_recoveries"] == []


def test_dry_run_creates_no_history(cache_file: tuple[Path, Path]) -> None:
    home, _ = cache_file
    executor.execute_cleanup(create_cleanup_plan(home), home=home)
    assert not (home / journal.HISTORY_ROOT).exists()


def test_unavailable_journal_blocks_cleanup(cache_file: tuple[Path, Path], monkeypatch) -> None:
    home, file = cache_file
    monkeypatch.setattr(executor, "create_journal", Mock(side_effect=PermissionError("Denied")))
    report = executor.execute_cleanup(
        create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
    )
    assert report.audit_error is not None
    assert report.bytes_removed == 0
    assert file.exists()


def test_journal_failure_after_staging_preserves_file(
    cache_file: tuple[Path, Path], monkeypatch
) -> None:
    home, file = cache_file
    original = journal.Journal.append

    def fail_staged(self, event, data):
        if event == "staged":
            raise OSError("Disk full")
        original(self, event, data)

    monkeypatch.setattr(journal.Journal, "append", fail_staged)
    report = executor.execute_cleanup(
        create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
    )
    result = report.results[0]
    assert result.status == "failed"
    assert result.recovery_path is not None
    assert result.recovery_path.exists()
    assert journal.read_history(home)[0]["potential_recoveries"]


def test_symlinked_history_directory_is_refused(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    parent = home / journal.HISTORY_ROOT.parent
    parent.mkdir(parents=True)
    external = home / "external"
    external.mkdir()
    (parent / journal.HISTORY_ROOT.name).symlink_to(external, target_is_directory=True)
    report = executor.execute_cleanup(
        create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
    )
    assert report.audit_error
    assert file.exists()
    assert list(external.iterdir()) == []


def test_malformed_history_is_data_not_instructions(tmp_path: Path) -> None:
    root = tmp_path / journal.HISTORY_ROOT
    root.mkdir(parents=True)
    (root / "bad.jsonl").write_text('{"unfinished":')
    assert "error" in journal.read_history(tmp_path)[0]


def test_audit_failure_after_deletion_keeps_actual_results_and_stops(
    cache_file, monkeypatch
) -> None:
    import os
    import time

    home, body = cache_file
    metadata = body.with_suffix("")
    metadata.write_bytes(b"metadata")
    old = time.time() - 8 * 86400
    os.utime(metadata, (old, old))
    plan = create_cleanup_plan(home)
    original = journal.Journal.append

    def fail_result(self, event, data):
        if event == "result":
            raise OSError("Journal write failed")
        original(self, event, data)

    monkeypatch.setattr(journal.Journal, "append", fail_result)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.audit_error
    assert [result.status for result in report.results] == ["deleted", "skipped"]
    assert report.bytes_removed == len(b"metadata")
    assert body.exists()


def test_truncated_record_preserves_prior_recovery_information(tmp_path: Path) -> None:
    root = tmp_path / journal.HISTORY_ROOT
    root.mkdir(parents=True)
    path = root / "interrupted.jsonl"
    path.write_text(
        json.dumps({"event": "intent", "data": {"path": "cache", "recovery_path": "saved"}})
        + '\n{"unfinished":'
    )
    result = journal.read_history(tmp_path)[0]
    assert result["error"]
    assert result["potential_recoveries"] == [{"path": "cache", "recovery_path": "saved"}]
