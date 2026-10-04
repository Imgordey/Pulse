from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pulse.core import processes


def test_samples_twice_and_skips_inaccessible_or_exited(monkeypatch):
    good = Mock(pid=12)
    good.name.return_value = "worker"
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
    assert result.processes == (processes.ProcessStats(12, "worker", 150.0, 1024),)
    assert result.skipped == 3
    assert good.cpu_percent.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_rejects_short_sample():
    with pytest.raises(ValueError):
        processes.get_process_stats(0)
