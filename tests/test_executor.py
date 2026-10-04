import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from pulse.cleanup import executor
from pulse.cleanup.models import Safety
from pulse.cleanup.planner import create_cleanup_plan


def test_dry_run_has_zero_filesystem_writes(cache_file: tuple[Path, Path], monkeypatch) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    for name in ("mkdir", "rename", "unlink", "rmdir"):
        monkeypatch.setattr(
            executor.os, name, Mock(side_effect=AssertionError("Dry run wrote files"))
        )
    report = executor.execute_cleanup(plan, home=home)
    assert report.dry_run
    assert report.results[0].status == "would_delete"
    assert report.bytes_removed == 0
    assert file.exists()


def test_real_cleanup_only_disposable_test_file(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    report = executor.execute_cleanup(
        create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
    )
    assert report.results[0].status == "deleted"
    assert report.bytes_removed == len(b"cache payload")
    assert report.bytes_reclaimed is None
    assert not file.exists()
    assert not list(file.parent.glob(".pulse-delete-*"))


def test_missing_confirmation_and_expired_incomplete_plans(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    for bad_plan in (plan, replace(plan, created_at=0), replace(plan, complete=False)):
        report = executor.execute_cleanup(bad_plan, dry_run=False, home=home)
        assert report.results[0].status == "skipped"
    assert file.exists()


def test_protected_root_and_path_traversal(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    bad = replace(plan, root=home / "Documents")
    assert executor.execute_cleanup(bad, home=home).results[0].status == "skipped"
    item = replace(plan.files[0], relative_path=Path("../../Documents/private"))
    bad = replace(plan, files=(item,))
    assert executor.execute_cleanup(bad, home=home).results[0].status == "skipped"
    protected = replace(plan.files[0], safety=Safety.protected)
    assert (
        executor.execute_cleanup(replace(plan, files=(protected,)), home=home).results[0].status
        == "skipped"
    )
    assert file.exists()


def test_changed_file_is_preserved(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    file.write_bytes(b"new user content")
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "skipped"
    assert file.read_bytes() == b"new user content"


def test_missing_file_is_skipped(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    file.unlink()
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "skipped"


def test_symlink_swap_does_not_touch_target(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    private = home / "private"
    private.write_bytes(b"private")
    file.unlink()
    file.symlink_to(private)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "skipped"
    assert private.read_bytes() == b"private"


def test_permission_failure_reported(cache_file: tuple[Path, Path], monkeypatch) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    monkeypatch.setattr(executor.os, "rename", Mock(side_effect=PermissionError("Denied")))
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "failed"
    assert file.exists()


def test_racing_replacement_is_preserved_not_deleted(
    cache_file: tuple[Path, Path], monkeypatch
) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    original_rename = os.rename

    def racing_rename(src, dst, **kwargs):
        file.write_bytes(b"changed concurrently")
        original_rename(src, dst, **kwargs)

    monkeypatch.setattr(executor.os, "rename", racing_rename)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    result = report.results[0]
    assert result.status == "failed"
    assert result.recovery_path is not None
    assert result.recovery_path.read_bytes() == b"changed concurrently"
    assert report.bytes_removed == 0


def test_empty_plan_does_nothing(tmp_path: Path) -> None:
    report = executor.execute_cleanup(create_cleanup_plan(tmp_path), home=tmp_path)
    assert report.results == ()
    assert report.bytes_removed == 0


def test_root_replaced_and_shared_directories_refused(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    root = plan.root
    root.rename(root.with_name("old-root"))
    root.mkdir()
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status in ("skipped", "failed")
    assert (root.with_name("old-root") / plan.files[0].relative_path).exists()


def test_shared_writable_parent_is_refused(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    file.parent.chmod(0o777)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "failed"
    assert file.exists()


def test_duplicate_entries_do_not_double_count(cache_file: tuple[Path, Path]) -> None:
    home, _ = cache_file
    plan = create_cleanup_plan(home)
    plan = replace(plan, files=plan.files * 2)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert [r.status for r in report.results] == ["deleted", "skipped"]
    assert report.bytes_removed == len(b"cache payload")


def test_symlinked_parent_is_refused(cache_file: tuple[Path, Path]) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    original_parent = file.parent
    saved_parent = original_parent.with_name("saved-parent")
    original_parent.rename(saved_parent)
    original_parent.symlink_to(saved_parent, target_is_directory=True)
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "failed"
    assert (saved_parent / file.name).exists()


def test_unlink_failure_preserves_staged_file(cache_file: tuple[Path, Path], monkeypatch) -> None:
    home, file = cache_file
    plan = create_cleanup_plan(home)
    monkeypatch.setattr(executor.os, "unlink", Mock(side_effect=PermissionError("Denied")))
    report = executor.execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    result = report.results[0]
    assert result.status == "failed"
    assert result.recovery_path is not None
    assert result.recovery_path.exists()
    assert report.bytes_removed == 0
