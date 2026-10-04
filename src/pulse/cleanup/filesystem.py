"""Descriptor-relative directory access for macOS/POSIX filesystem safety."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def open_directory(path: Path) -> Iterator[int]:
    """Open every absolute path component without following symlinks."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("An absolute path without parent traversal is required")
    descriptor = os.open(path.anchor, DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def valid_relative(path: Path) -> bool:
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


@contextmanager
def open_relative_directory(root_fd: int, relative: Path) -> Iterator[int]:
    if relative != Path(".") and not valid_relative(relative):
        raise ValueError("Invalid relative directory")
    descriptor = os.dup(root_fd)
    try:
        for part in relative.parts:
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def validate_owned_directory_chain(home: Path, parent: Path) -> None:
    relative = parent.relative_to(home)
    current = home
    for component in (None, *relative.parts):
        if component is not None:
            current /= component
        with open_directory(current) as fd:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise PermissionError(
                    "Cache directories must be owned by you and not shared-writable"
                )
