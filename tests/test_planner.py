import os
import time
from pathlib import Path

import pytest

from pulse.cleanup.models import Safety
from pulse.cleanup.planner import classify_file, create_cleanup_plan


def test_plan_only_old_known_cache(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    assert plan.complete
    assert plan.estimated_bytes == len(b"cache payload")
    assert len(plan.files) == 1
    assert plan.files[0].safety == Safety.safe
    assert file.exists()


def test_unknown_files_are_protected(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    unknown = file.parent / "credentials"
    unknown.write_bytes(b"never delete")
    assert classify_file(Path("credentials"), unknown.stat(), time.time())[0] == Safety.protected
    assert len(create_cleanup_plan(home).files) == 1


def test_recent_files_and_hardlinks_are_not_planned(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    os.utime(file, None)
    assert create_cleanup_plan(home).files == ()
    old = time.time() - 8 * 86400
    os.utime(file, (old, old))
    os.link(file, file.parent / "shared")
    assert create_cleanup_plan(home).files == ()


def test_symlinked_ancestor_and_root_are_refused(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    directory = home / "Library/Caches/pip/http-v2"
    directory.rename(directory.with_name("original"))
    directory.symlink_to(directory.with_name("original"), target_is_directory=True)
    assert not create_cleanup_plan(home).complete
    assert file.exists()


def test_missing_and_bounded_plan(tmp_path: Path, cache_file: tuple[Path, Path]) -> None:
    assert not create_cleanup_plan(tmp_path / "missing").complete
    home, _ = cache_file
    plan = create_cleanup_plan(home, max_entries=1)
    assert not plan.complete
    assert not plan.files
    with pytest.raises(ValueError):
        create_cleanup_plan(home, max_entries=0)


def test_replaced_subdirectory_is_not_planned(cache_file, monkeypatch):
    from contextlib import contextmanager

    from pulse.cleanup import planner

    home, file = cache_file
    other = home / "replacement"
    other.mkdir()
    original = planner.open_relative_directory

    @contextmanager
    def replaced(fd, relative):
        if relative == Path("a"):
            with planner.open_directory(other) as replacement:
                yield replacement
        else:
            with original(fd, relative) as child:
                yield child

    monkeypatch.setattr(planner, "open_relative_directory", replaced)
    result = planner.create_cleanup_plan(home)
    assert not result.complete and not result.files
    assert any("changed" in warning for warning in result.warnings)
    assert file.exists()
