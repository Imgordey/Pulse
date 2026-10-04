from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Safety(StrEnum):
    safe = "safe"
    review = "review"
    protected = "protected"


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    owner: int
    links: int


@dataclass(frozen=True)
class PlannedFile:
    relative_path: Path
    identity: FileIdentity
    safety: Safety
    reason: str


@dataclass(frozen=True)
class CleanupPlan:
    home: Path
    root: Path
    root_device: int
    root_inode: int
    files: tuple[PlannedFile, ...]
    skipped: int
    complete: bool
    created_at: float
    warnings: tuple[str, ...] = ()

    @property
    def estimated_bytes(self) -> int:
        return sum(file.identity.size for file in self.files)


@dataclass(frozen=True)
class CleanupResult:
    path: Path
    status: str
    reason: str
    bytes_removed: int = 0
    recovery_path: Path | None = None


@dataclass(frozen=True)
class CleanupReport:
    results: tuple[CleanupResult, ...]
    dry_run: bool
    bytes_removed: int
    bytes_reclaimed: int | None
