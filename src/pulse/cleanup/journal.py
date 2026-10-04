"""Private, append-only per-run audit records, synced before file mutations."""

import json
import os
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pulse.cleanup.filesystem import DIRECTORY_FLAGS, open_directory

HISTORY_ROOT = Path("Library/Application Support/Pulse/cleanup-history")


def check_private_directory(fd: int) -> None:
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise PermissionError("Journal directories must be owned by you and not shared-writable")


@dataclass
class Journal:
    path: Path
    stream: TextIO

    def append(self, event: str, data: dict[str, object]) -> None:
        self.stream.write(
            json.dumps(
                {"version": 1, "time": time.time(), "event": event, "data": data}, default=str
            )
            + "\n"
        )
        self.stream.flush()
        os.fsync(self.stream.fileno())


@contextmanager
def create_journal(home: Path) -> Iterator[Journal]:
    with open_directory(home) as home_fd:
        check_private_directory(home_fd)
        directory_fd = os.dup(home_fd)
        try:
            for part in HISTORY_ROOT.parts:
                try:
                    os.mkdir(part, 0o700, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except FileExistsError:
                    pass
                child = os.open(part, DIRECTORY_FLAGS, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child
                check_private_directory(directory_fd)
            name = f"{uuid.uuid4().hex}.jsonl"
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.fsync(directory_fd)
                yield Journal(home / HISTORY_ROOT / name, stream)
        finally:
            os.close(directory_fd)


def read_history(home: Path | None = None, limit: int = 20) -> tuple[dict[str, object], ...]:
    """Read bounded summaries; history is untrusted data, never executable plans."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    home = Path.home() if home is None else home
    reports: list[dict[str, object]] = []
    try:
        with open_directory(home / HISTORY_ROOT) as directory_fd:
            check_private_directory(directory_fd)
            names: list[tuple[int, str]] = []
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if entry.name.endswith(".jsonl"):
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISREG(info.st_mode):
                                names.append((info.st_mtime_ns, entry.name))
                        except OSError:
                            continue
            names = sorted(names, reverse=True)[:limit]
            for _, name in names:
                pending: dict[str, dict[str, object]] = {}
                try:
                    fd = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
                    )
                    with os.fdopen(fd, "r", encoding="utf-8") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024**2:
                            continue
                        last = None
                        for line in stream:
                            if len(line) > 1024 * 1024:
                                raise ValueError("History record exceeds size limit")
                            record = json.loads(line)
                            if not isinstance(record, dict):
                                raise ValueError("Invalid journal record")
                            last = record
                            data = record.get("data", {})
                            if not isinstance(data, dict):
                                raise ValueError("Invalid journal payload")
                            path = data.get("path")
                            if isinstance(path, str):
                                if data.get("recovery_path"):
                                    pending[path] = {
                                        "path": path,
                                        "recovery_path": data["recovery_path"],
                                    }
                                elif record.get("event") == "result":
                                    pending.pop(path, None)
                        reports.append(
                            {
                                "journal": name,
                                "last_event": last,
                                "potential_recoveries": list(pending.values()),
                            }
                        )
                except (OSError, ValueError, UnicodeError) as exc:
                    reports.append(
                        {
                            "journal": name,
                            "error": str(exc),
                            "potential_recoveries": list(pending.values()),
                        }
                    )
    except FileNotFoundError:
        return ()
    return tuple(reports)
