from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Safety(StrEnum):
    safe = "safe"
    review = "review"
    protected = "protected"


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    category: str
    size: int
    description: str
    risk_level: str
    removable: bool
    reason: str
    complete: bool
    skipped: int
    id: str = ""
    safety: Safety = Safety.review
    allocated_bytes: int = 0
    files: int = 0
    exclusions: dict[str, int] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        return self.size


@dataclass(frozen=True)
class ScanProblem:
    path: Path
    reason: str


@dataclass(frozen=True)
class StorageScan:
    candidates: tuple[CleanupCandidate, ...]
    problems: tuple[ScanProblem, ...]
    complete: bool = True
    cancelled: bool = False
    unscanned: tuple[Path, ...] = ()
    inspected: int = 0
    elapsed_seconds: float = 0


@dataclass(frozen=True)
class ScanProgress:
    location: Path
    inspected: int
    logical_bytes: int
    locations_done: int
    total_locations: int


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
    category: str = "pip-http"

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
    blocked_reason: str | None = None
    journal_path: Path | None = None
    audit_error: str | None = None
