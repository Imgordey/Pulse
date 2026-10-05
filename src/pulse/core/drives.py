"""Read physical-drive information reported by macOS; never repair, erase or mount disks."""

import plistlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from xml.parsers.expat import ExpatError


@dataclass(frozen=True)
class DriveStats:
    identifier: str
    model: str | None
    protocol: str | None
    total_bytes: int | None
    internal: bool | None
    solid_state: bool | None
    smart_status: str | None
    smart_attributes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DriveSnapshot:
    drives: tuple[DriveStats, ...]
    problems: tuple[str, ...]
    complete: bool


def _read_plist(arguments: tuple[str, ...], timeout: float) -> dict:
    completed = subprocess.run(
        ("/usr/sbin/diskutil", *arguments),
        capture_output=True,
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode:
        raise OSError(
            completed.stderr.decode("utf-8", errors="replace")[:1000].strip()
            or "macOS disk information is unavailable"
        )
    if len(completed.stdout) > 4 * 1024 * 1024:
        raise ValueError("Disk information exceeded the response limit")
    try:
        data = plistlib.loads(completed.stdout)
    except (ValueError, plistlib.InvalidFileException, ExpatError) as exc:
        raise ValueError("Malformed disk information") from exc
    if not isinstance(data, dict):
        raise ValueError("Unexpected disk information format")
    return data


def get_drives(*, max_seconds: float = 15) -> DriveSnapshot:
    if not 0 < max_seconds <= 60:
        raise ValueError("Invalid drive discovery time budget")
    if sys.platform != "darwin":
        return DriveSnapshot((), ("Physical drive information requires macOS",), False)
    deadline = time.monotonic() + max_seconds
    drives = []
    problems = []

    def read(*arguments: str) -> dict:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Drive discovery time limit reached")
        return _read_plist(arguments, min(5, remaining))

    try:
        listing = read("list", "-plist", "physical")
        identifiers = listing.get("WholeDisks")
        if not isinstance(identifiers, list):
            raise ValueError("Physical disk list is missing")
        if len(identifiers) > 32:
            problems.append("Only the first 32 physical disks were inspected")
        seen = set()
        for identifier in identifiers[:32]:
            if not isinstance(identifier, str) or not re.fullmatch(r"disk[0-9]+", identifier):
                problems.append("Unexpected physical disk identifier was ignored")
                continue
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                data = read("info", "-plist", identifier)
                if data.get("DeviceIdentifier") != identifier or data.get("WholeDisk") is not True:
                    raise ValueError("Disk identity changed or response is not a whole disk")
                size = data.get("TotalSize")
                size = size if type(size) is int and 0 <= size <= 2**64 else None
                raw = data.get("SMARTDeviceSpecificKeysMayVaryNotGuaranteed", {})
                attributes = (
                    {
                        key: value
                        for key, value in raw.items()
                        if isinstance(key, str) and type(value) is int and 0 <= value <= 2**128
                    }
                    if isinstance(raw, dict)
                    else {}
                )

                drives.append(
                    DriveStats(
                        identifier,
                        _string(data, "MediaName"),
                        _string(data, "BusProtocol"),
                        size,
                        data.get("Internal") if type(data.get("Internal")) is bool else None,
                        data.get("SolidState") if type(data.get("SolidState")) is bool else None,
                        _string(data, "SMARTStatus"),
                        attributes,
                    )
                )
            except (
                OSError,
                ValueError,
                plistlib.InvalidFileException,
                subprocess.TimeoutExpired,
            ) as exc:
                problems.append(f"{identifier}: {exc}")
                if time.monotonic() >= deadline:
                    break
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.TimeoutExpired) as exc:
        problems.append(str(exc))
    return DriveSnapshot(tuple(drives), tuple(problems), not problems)


def _string(data: dict, key: str) -> str | None:
    value = data.get(key)
    return value[:256] if isinstance(value, str) and value else None
