from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pulse.core import processes


def test_samples_twice_and_skips_inaccessible_or_exited(monkeypatch):
    good = Mock(pid=12)
    good.name.return_value = "worker"
    good.username.return_value = "test-user"
    good.cpu_percent.side_effect = [0, 150.0]
    good.memory_info.return_value = SimpleNamespace(rss=1024)
    denied = Mock(pid=13)
    denied.cpu_percent.side_effect = psutil.AccessDenied(13)
    exited = Mock(pid=14)
    exited.is_running.return_value = False
    vanished = Mock(pid=15)
    vanished.name.side_effect = psutil.NoSuchProcess(15)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([good, denied, exited, vanished]))
    sleep = Mock()
    monkeypatch.setattr(processes.time, "sleep", sleep)
    result = processes.get_process_stats()
    assert result.processes == (processes.ProcessStats(12, "worker", 150.0, 1024, "test-user"),)
    assert result.skipped == 3
    assert good.cpu_percent.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_rejects_short_sample():
    with pytest.raises(ValueError):
        processes.get_process_stats(0)


def test_listing_permission_error_returns_unavailable_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(psutil, "process_iter", Mock(side_effect=PermissionError("Denied")))
    snapshot = processes.get_process_stats()
    assert snapshot.processes == ()
    assert snapshot.error is not None


def test_username_permission_does_not_drop_process(monkeypatch) -> None:
    good = Mock(pid=12)
    good.name.return_value = "worker"
    good.username.side_effect = psutil.AccessDenied(12)
    good.cpu_percent.return_value = 10.0
    good.memory_info.return_value = SimpleNamespace(rss=1024)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([good]))
    monkeypatch.setattr(processes.time, "sleep", lambda _: None)
    snapshot = processes.get_process_stats()
    assert snapshot.processes[0].user is None
    assert snapshot.skipped == 0
