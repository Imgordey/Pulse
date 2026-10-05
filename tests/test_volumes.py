from types import SimpleNamespace

from pulse.core import volumes


def test_apfs_volumes_are_individual_and_inaccessible_not_zero(monkeypatch):
    entries = [
        SimpleNamespace(device="disk1", mountpoint="/", fstype="apfs", opts="ro"),
        SimpleNamespace(device="disk2", mountpoint="/private", fstype="apfs", opts="rw"),
    ]
    monkeypatch.setattr(volumes.psutil, "disk_partitions", lambda all: entries)

    def usage(path):
        if path == "/private":
            raise PermissionError("denied")
        return SimpleNamespace(total=100, used=40, free=60)

    monkeypatch.setattr(volumes.psutil, "disk_usage", usage)
    results = volumes.get_volumes()
    assert results[0].free == 60
    assert results[1].free is None and results[1].error == "denied"
