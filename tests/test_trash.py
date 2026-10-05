import os
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from pulse.cleanup.journal import read_history
from pulse.cleanup.recovery import prepare_recovery, recover_file
from pulse.storage.trash import execute_trash, prepare_trash


@pytest.fixture
def download(tmp_path):
    home = tmp_path / "home"
    file = home / "Downloads" / "installer.dmg"
    file.parent.mkdir(parents=True, mode=0o700)
    file.write_bytes(b"test download")
    return home, file


def test_no_confirmation_never_calls_adapter(download):
    home, file = download
    adapter = Mock()
    result = execute_trash(prepare_trash(file, home=home), move_to_trash=adapter, home=home)
    assert result.status == "cancelled" and file.exists()
    adapter.assert_not_called()
    assert not read_history(home)


def test_move_preserves_name_and_journals_zero_reclaimed(download, tmp_path):
    home, file = download
    trash = tmp_path / "native-trash"
    trash.mkdir()

    def adapter(source):
        assert source.name == file.name
        destination = trash / source.name
        source.rename(destination)
        return destination

    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "trashed" and not file.exists()
    assert result.trash_path.read_bytes() == b"test download"
    assert not tuple(file.parent.glob(".pulse-delete-*"))
    assert read_history(home)[0]["last_event"]["data"]["bytes_removed"] == 0


def test_failed_native_trash_preserves_and_recovery_does_not_overwrite(download):
    home, file = download
    adapter = Mock(side_effect=OSError("Trash unavailable"))
    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "failed" and not file.exists()
    assert result.recovery_path.read_bytes() == b"test download"
    assert read_history(home)[0]["potential_recoveries"][0]["path"] == str(file)
    plan = prepare_recovery(result.recovery_path, file, home=home)
    file.write_bytes(b"new download")
    assert recover_file(plan, dry_run=False, confirmed=True, home=home).status == "failed"
    assert file.read_bytes() == b"new download"
    file.unlink()
    restored = recover_file(plan, dry_run=False, confirmed=True, home=home)
    assert restored.status == "restored" and file.read_bytes() == b"test download"


def test_changed_file_or_expired_plan_refuses(download):
    home, file = download
    plan = prepare_trash(file, home=home)
    adapter = Mock()
    expired = replace(plan, created_at=time.time() - 901)
    assert (
        execute_trash(expired, move_to_trash=adapter, confirmed=True, home=home).status == "failed"
    )
    file.write_bytes(b"new contents")
    assert execute_trash(plan, move_to_trash=adapter, confirmed=True, home=home).status == "failed"
    assert file.read_bytes() == b"new contents"
    adapter.assert_not_called()


def test_symlinks_hidden_outside_packages_and_hardlinks_refused(download):
    home, file = download
    paths = [home / "outside", file.parent / ".secret", file.parent / "My.app" / "data"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"protected")
        with pytest.raises(ValueError):
            prepare_trash(path, home=home)
    linked = file.parent / "linked"
    linked.symlink_to(file)
    with pytest.raises(ValueError):
        prepare_trash(linked, home=home)
    linked.unlink()
    os.link(file, linked)
    with pytest.raises(ValueError):
        prepare_trash(file, home=home)


def test_journal_failure_prevents_any_move(download, monkeypatch):
    from pulse.cleanup.journal import Journal

    home, file = download
    adapter = Mock()
    monkeypatch.setattr(Journal, "append", Mock(side_effect=OSError("Full disk")))
    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "failed" and result.audit_error and file.exists()
    adapter.assert_not_called()


def test_racing_replacement_preserved_never_trashed(download, monkeypatch):
    from pulse.storage import trash

    home, file = download
    plan = prepare_trash(file, home=home)
    original_rename = os.rename

    def racing_rename(*args, **kwargs):
        file.unlink()
        file.write_bytes(b"racing replacement")
        original_rename(*args, **kwargs)

    monkeypatch.setattr(trash.os, "rename", racing_rename)
    adapter = Mock()
    result = execute_trash(plan, move_to_trash=adapter, confirmed=True, home=home)
    assert result.status == "failed"
    assert result.recovery_path.read_bytes() == b"racing replacement"
    adapter.assert_not_called()


def test_history_can_restore_native_trash_without_overwriting(download):
    home, file = download
    trash = home / ".Trash"
    trash.mkdir(mode=0o700)

    def adapter(source):
        target = trash / "installer 2.dmg"
        source.rename(target)
        return target

    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    record = read_history(home)[0]
    assert record["potential_recoveries"][0]["recovery_path"] == str(result.trash_path)
    plan = prepare_recovery(result.trash_path, file, home=home)
    assert recover_file(plan, dry_run=False, confirmed=True, home=home).status == "restored"
    assert file.read_bytes() == b"test download" and not result.trash_path.exists()


def test_native_trash_adapter_must_actually_move(download):
    home, file = download
    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=lambda _: None, confirmed=True, home=home
    )
    assert result.status == "failed" and result.recovery_path.exists()


def test_native_error_after_move_reports_uncertain(download, tmp_path):
    home, file = download
    target = tmp_path / "trashed"

    def adapter(source):
        source.rename(target)
        raise OSError("Native result unavailable")

    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "uncertain" and result.recovery_path is None
    assert target.read_bytes() == b"test download"


def test_final_audit_failure_retains_completed_result(download, tmp_path, monkeypatch):
    from pulse.cleanup.journal import Journal

    home, file = download
    target = tmp_path / "trashed"
    append = Journal.append

    def fail_final(self, event, data):
        if event == "finished":
            raise OSError("Final audit failed")
        return append(self, event, data)

    monkeypatch.setattr(Journal, "append", fail_final)

    def adapter(source):
        source.rename(target)
        return target

    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "trashed" and result.audit_error
    assert result.trash_path == target and not file.exists()


def test_shared_download_directory_refused(download):
    home, file = download
    file.parent.chmod(0o777)
    try:
        with pytest.raises(PermissionError):
            prepare_trash(file, home=home)
    finally:
        file.parent.chmod(0o700)


@pytest.mark.parametrize("folder", ["Desktop", "Documents", "Movies", "Music", "Pictures"])
def test_personal_file_can_be_reviewed_and_restored(tmp_path, folder):
    home = tmp_path / "home"
    file = home / folder / "ordinary-file.txt"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"personal fixture")
    trash = home / ".Trash"
    trash.mkdir(mode=0o700)

    def adapter(source):
        target = trash / source.name
        source.rename(target)
        return target

    result = execute_trash(
        prepare_trash(file, home=home), move_to_trash=adapter, confirmed=True, home=home
    )
    assert result.status == "trashed"
    plan = prepare_recovery(result.trash_path, file, home)
    assert recover_file(plan, dry_run=False, confirmed=True, home=home).status == "restored"
    assert file.read_bytes() == b"personal fixture"


@pytest.mark.parametrize(
    "relative",
    [
        "Documents/Secret.app/Contents/data",
        "Pictures/Photos.photoslibrary/originals/file",
        "Documents/.ssh/key",
        "Documents/.git/config",
        "Library/Caches/file",
        "Documents/Book.pages/Data/file",
        "Movies/Machine.vmwarevm/disk",
        "Documents/../outside",
    ],
)
def test_hidden_system_and_package_paths_remain_protected(tmp_path, relative):
    from pulse.storage.trash import personal_file_scope

    assert not personal_file_scope(tmp_path / relative, tmp_path)


def test_regular_document_with_package_extension_can_be_reviewed(tmp_path):
    file = tmp_path / "Documents" / "Book.pages"
    file.parent.mkdir()
    file.write_bytes(b"a regular document archive, not a directory")
    assert prepare_trash(file, home=tmp_path).path == file


def test_cli_trash_preview_and_cancel_never_execute(download, monkeypatch):
    from typer.testing import CliRunner

    from pulse.cli import app
    from pulse.presentation import storage

    home, file = download
    monkeypatch.setattr(storage, "prepare_trash", lambda path: prepare_trash(path, home=home))
    action = Mock()
    monkeypatch.setattr(storage, "execute_trash", action)
    assert CliRunner().invoke(app, ["trash", str(file), "--dry-run", "--json"]).exit_code == 0
    result = CliRunner().invoke(app, ["trash", str(file)], input="n\n")
    assert result.exit_code == 0 and "Cancelled" in result.stdout
    action.assert_not_called()
    assert file.exists()
