import os
from pathlib import Path
from threading import Event

import pytest

from pulse.storage.analyzer import analyze_directory


def test_nested_sizes_largest_and_no_contents_read(tmp_path, monkeypatch):
    nested = tmp_path / "folder"
    nested.mkdir()
    (nested / "large").write_bytes(b"x" * 9000)
    (tmp_path / "small").write_bytes(b"abc")
    monkeypatch.setattr(Path, "read_bytes", lambda _: pytest.fail("Must not read contents"))
    result = analyze_directory(tmp_path, largest_limit=1)
    assert result.complete and result.files == 2 and result.logical_bytes == 9003
    assert result.largest_files[0].path == nested / "large"
    assert result.children[0].directory and result.children[0].files == 1
    assert result.allocated_bytes == sum(
        p.stat().st_blocks * 512 for p in (nested / "large", tmp_path / "small")
    )


def test_sparse_file_distinguishes_logical_and_allocated(tmp_path):
    file = tmp_path / "sparse"
    with file.open("wb") as stream:
        stream.truncate(10 * 1024**2)
    result = analyze_directory(tmp_path)
    assert result.logical_bytes == 10 * 1024**2
    assert result.allocated_bytes < result.logical_bytes


def test_links_are_not_followed_and_hard_links_count_once(tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"data")
    os.link(original, tmp_path / "hardlink")
    (tmp_path / "symlink").symlink_to(original)
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    result = analyze_directory(tmp_path)
    assert result.logical_bytes == 4 and result.files == 1
    assert result.exclusions == {"symbolic links": 2, "duplicate hard links": 1}
    assert not result.complete


def test_symlinked_root_or_ancestor_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "child").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    for root in (link, link / "child"):
        result = analyze_directory(root)
        assert not result.complete and result.problems and result.inspected == 0


def test_budget_is_partial_and_does_not_overcount(tmp_path):
    for index in range(10):
        (tmp_path / str(index)).write_bytes(b"abc")
    result = analyze_directory(tmp_path, max_entries=3)
    assert result.inspected == 3 and result.logical_bytes == 9
    assert not result.complete and result.exclusions["scan budget reached"] == 1


def test_cancel_before_start_and_during_progress(tmp_path):
    cancelled = Event()
    cancelled.set()
    result = analyze_directory(tmp_path, cancel=cancelled)
    assert result.cancelled and not result.complete and result.inspected == 0
    cancelled.clear()
    for index in range(1001):
        (tmp_path / str(index)).touch()
    updates = []

    def progress(update):
        updates.append(update)
        cancelled.set()

    result = analyze_directory(tmp_path, cancel=cancelled, progress=progress)
    assert result.cancelled and result.inspected == 1000
    assert updates[-1].inspected == 1000


def test_skips_trash_staging_and_special_files(tmp_path):
    for name in (".Trash", ".pulse-delete-test"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "secret").write_bytes(b"do not inspect")
    os.mkfifo(tmp_path / "pipe")
    result = analyze_directory(tmp_path)
    assert result.files == 0 and not result.complete
    assert result.exclusions["trash or recovery staging"] == 2
    assert result.exclusions["special files"] == 1


def test_missing_directory_has_honest_partial_result(tmp_path):
    result = analyze_directory(tmp_path / "missing")
    assert result.problems and result.files == 0 and not result.complete


def test_invalid_budgets_and_traversal(tmp_path):
    for options in ({"max_entries": 0}, {"max_seconds": 0}, {"largest_limit": 0}):
        with pytest.raises(ValueError):
            analyze_directory(tmp_path, **options)
    with pytest.raises(ValueError):
        analyze_directory(tmp_path / "..")


def test_cli_analyze_json_and_missing_directory(tmp_path):
    import json

    from typer.testing import CliRunner

    from pulse.cli import app

    (tmp_path / "file").write_bytes(b"fixture")
    result = CliRunner().invoke(app, ["analyze", str(tmp_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["logical_bytes"] == 7 and data["complete"]
    missing = CliRunner().invoke(app, ["analyze", str(tmp_path / "missing"), "--json"])
    assert missing.exit_code == 1 and json.loads(missing.stdout)["problems"]


def test_unreadable_child_is_partial_and_visible(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from pulse.storage import analyzer

    directory = tmp_path / "unreadable"
    directory.mkdir()
    (directory / "hidden").write_bytes(b"not counted")
    original = analyzer.open_relative_directory

    @contextmanager
    def inaccessible(fd, relative):
        if relative == Path("unreadable"):
            raise PermissionError("Access denied")
        with original(fd, relative) as child:
            yield child

    monkeypatch.setattr(analyzer, "open_relative_directory", inaccessible)
    result = analyze_directory(tmp_path)
    assert not result.complete and result.logical_bytes == 0
    assert "Access denied" in result.problems[0]


def test_elapsed_time_budget_stops_before_file_walk(tmp_path, monkeypatch):
    from pulse.storage import analyzer

    readings = iter([0, 2, 2])
    monkeypatch.setattr(analyzer.time, "monotonic", lambda: next(readings))
    result = analyze_directory(tmp_path, max_seconds=1)
    assert not result.complete and result.inspected == 0
    assert result.exclusions["scan budget reached"] == 1


def test_hardlink_deduplication_does_not_mean_incomplete_coverage(tmp_path):
    file = tmp_path / "first"
    file.write_bytes(b"one inode")
    os.link(file, tmp_path / "second")
    result = analyze_directory(tmp_path)
    assert result.complete and result.files == 1 and result.logical_bytes == 9
    assert result.exclusions["duplicate hard links"] == 1
