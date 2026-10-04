import pytest

from pulse.cleanup.recovery import prepare_recovery, recover_file


def test_restore_without_overwriting(preserved_file) -> None:
    home, source, destination = preserved_file
    plan = prepare_recovery(source, destination, home)
    preview = recover_file(plan, home=home)
    assert preview.status == "would_restore"
    assert source.exists()
    assert not destination.exists()
    result = recover_file(plan, dry_run=False, confirmed=True, home=home)
    assert result.status == "restored"
    assert destination.read_bytes() == b"cache payload"
    assert not source.exists()
    assert result.journal_path is not None


def test_conflicting_destination_is_never_overwritten(preserved_file) -> None:
    home, source, destination = preserved_file
    plan = prepare_recovery(source, destination, home)
    destination.write_bytes(b"new cache data")
    result = recover_file(plan, dry_run=False, confirmed=True, home=home)
    assert result.status == "failed"
    assert source.exists()
    assert destination.read_bytes() == b"new cache data"


def test_changed_recovery_and_missing_confirmation(preserved_file) -> None:
    home, source, destination = preserved_file
    plan = prepare_recovery(source, destination, home)
    assert recover_file(plan, dry_run=False, home=home).status == "skipped"
    source.write_bytes(b"changed")
    assert recover_file(plan, dry_run=False, confirmed=True, home=home).status == "failed"
    assert not destination.exists()


def test_protected_destination_and_symlinked_source(preserved_file) -> None:
    home, source, destination = preserved_file
    with pytest.raises(ValueError):
        prepare_recovery(source, home / "Documents/personal", home)
    source.unlink()
    target = home / "secret"
    target.write_bytes(b"private")
    source.symlink_to(target)
    with pytest.raises(ValueError):
        prepare_recovery(source, destination, home)
    assert target.read_bytes() == b"private"
