import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from pulse.cleanup import executor
from pulse.cleanup.planner import PIP_ROOT, create_cleanup_plan


@pytest.fixture
def cache_file(tmp_path: Path) -> tuple[Path, Path]:
    hashed = "abcde" + "0" * 51
    file = tmp_path / PIP_ROOT / Path(*hashed[:5]) / f"{hashed}.body"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"cache payload")
    old = time.time() - 8 * 86400
    os.utime(file, (old, old))
    return tmp_path, file


@pytest.fixture
def preserved_file(cache_file: tuple[Path, Path], monkeypatch):
    home, file = cache_file
    with monkeypatch.context() as patch:
        patch.setattr(executor.os, "unlink", Mock(side_effect=PermissionError("Denied")))
        report = executor.execute_cleanup(
            create_cleanup_plan(home), dry_run=False, confirmed=True, home=home
        )
    source = report.results[0].recovery_path
    assert source is not None
    return home, source, file
