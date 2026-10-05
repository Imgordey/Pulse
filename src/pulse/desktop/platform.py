"""Native macOS adapters; Qt remains outside the domain engine."""

import sys
from pathlib import Path

from PySide6.QtCore import QFile


def move_to_trash(path: Path) -> Path | None:
    if sys.platform != "darwin" or not QFile.supportsMoveToTrash():
        raise OSError("Native macOS Trash is unavailable; no permanent deletion was attempted")
    file = QFile(str(path))
    if not file.moveToTrash():
        raise OSError(file.errorString())
    return Path(file.fileName()) if file.fileName() else None
