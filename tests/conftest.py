import os
import time
from pathlib import Path

import pytest

from pulse.cleanup.planner import PIP_ROOT


@pytest.fixture
def cache_file(tmp_path: Path) -> tuple[Path, Path]:
    hashed = "abcde" + "0" * 51
    file = tmp_path / PIP_ROOT / Path(*hashed[:5]) / f"{hashed}.body"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"cache payload")
    old = time.time() - 8 * 86400
    os.utime(file, (old, old))
    return tmp_path, file
