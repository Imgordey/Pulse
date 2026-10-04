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
