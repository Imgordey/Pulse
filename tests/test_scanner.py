from pathlib import Path

import pytest

from pulse.cleanup.scanner import scan_cleanup


def test_scan_is_read_only_and_ignores_unknown_data(tmp_path: Path) -> None:
    cache = tmp_path / "Library/Caches/pip"
    cache.mkdir(parents=True)
    file = cache / "download"
    file.write_bytes(b"12345")
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents/personal").write_bytes(b"secret")
    result = scan_cleanup(tmp_path)
    assert len(result) == 1
    assert result[0].size == 5
    assert result[0].complete
    assert not result[0].removable
    assert file.read_bytes() == b"12345"


def test_symlinked_cache_root_is_not_scanned(tmp_path: Path) -> None:
    external = tmp_path / "documents"
    external.mkdir()
    (external / "private").write_bytes(b"secret")
    parent = tmp_path / "Library/Caches"
    parent.mkdir(parents=True)
    (parent / "pip").symlink_to(external, target_is_directory=True)
    assert scan_cleanup(tmp_path) == []


def test_symlink_children_and_hardlinks(tmp_path: Path) -> None:
    import os

    cache = tmp_path / "Library/Caches/pip"
    cache.mkdir(parents=True)
    file = cache / "download"
    file.write_bytes(b"12345")
    os.link(file, cache / "duplicate")
    (cache / "outside").symlink_to(tmp_path, target_is_directory=True)
    result = scan_cleanup(tmp_path)[0]
    assert result.size == 5
    assert result.skipped == 1
    assert not result.complete


def test_scan_budget_is_bounded(tmp_path: Path) -> None:
    cache = tmp_path / "Library/Caches/pip"
    cache.mkdir(parents=True)
    for i in range(3):
        (cache / str(i)).write_bytes(b"x")
    result = scan_cleanup(tmp_path, max_entries=1)[0]
    assert result.size == 1
    assert not result.complete
    with pytest.raises(ValueError):
        scan_cleanup(tmp_path, max_entries=0)


def test_trash_is_inspection_only(tmp_path: Path) -> None:
    from pulse.cleanup.models import Safety

    trash = tmp_path / ".Trash"
    trash.mkdir()
    file = trash / "personal-photo"
    file.write_bytes(b"personal content")
    result = scan_cleanup(tmp_path)[0]
    assert result.safety == Safety.protected
    assert not result.removable
    assert file.read_bytes() == b"personal content"


def test_recovery_directories_are_excluded(tmp_path: Path) -> None:
    cache = tmp_path / "Library/Caches/pip"
    staged = cache / ".pulse-delete-recovery"
    staged.mkdir(parents=True)
    (staged / "payload").write_bytes(b"preserve me")
    result = scan_cleanup(tmp_path)[0]
    assert result.size == 0
    assert not result.complete


def test_inaccessible_roots_reported(tmp_path: Path, monkeypatch) -> None:
    from contextlib import contextmanager

    from pulse.cleanup import scanner

    @contextmanager
    def denied(_):
        raise PermissionError("Protected by OS")
        yield

    monkeypatch.setattr(scanner, "open_directory", denied)
    report = scanner.scan_storage(tmp_path)
    assert report.candidates == ()
    assert report.problems


def test_additional_application_caches_are_inspection_only(tmp_path):
    from pulse.cleanup.scanner import scan_storage

    directory = tmp_path / "Library/Caches/com.example.app"
    directory.mkdir(parents=True)
    file = directory / "blob"
    file.write_bytes(b"1234567")
    result = scan_storage(tmp_path)
    assert result.complete and len(result.candidates) == 1
    entry = result.candidates[0]
    assert entry.files == 1 and entry.size == 7
    assert entry.allocated_bytes == file.stat().st_blocks * 512
    assert not entry.removable


def test_cancelled_inventory_returns_unscanned_locations(tmp_path):
    from threading import Event

    from pulse.cleanup.scanner import scan_storage

    cancel = Event()
    cancel.set()
    result = scan_storage(tmp_path, cancel=cancel)
    assert result.cancelled and not result.complete
    assert result.unscanned and not result.candidates


def test_inventory_time_budget_is_global(tmp_path, monkeypatch):
    from pulse.cleanup import scanner

    clock = iter([0, 2, 2])
    monkeypatch.setattr(scanner.time, "monotonic", lambda: next(clock))
    result = scanner.scan_storage(tmp_path, max_seconds=1)
    assert not result.complete and result.unscanned


def test_inventory_reports_progress_and_cancel_without_writes(tmp_path):
    from threading import Event

    from pulse.cleanup.scanner import scan_storage

    directory = tmp_path / "Library/Caches/pip"
    directory.mkdir(parents=True)
    for index in range(1002):
        (directory / str(index)).write_bytes(b"cache")
    cancel = Event()
    updates = []

    def progress(value):
        updates.append(value)
        cancel.set()

    result = scan_storage(tmp_path, cancel=cancel, progress=progress)
    assert result.cancelled and not result.complete and result.inspected == 1000
    assert len(list(directory.iterdir())) == 1002
    assert updates[-1].inspected == 1000
