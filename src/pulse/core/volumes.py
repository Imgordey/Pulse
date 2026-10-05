"""Accessible mounted volumes. APFS shared capacity is deliberately not added together."""

from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class VolumeStats:
    device: str
    mountpoint: str
    filesystem: str
    total: int | None
    used: int | None
    free: int | None
    options: str
    error: str | None = None


def get_volumes() -> tuple[VolumeStats, ...]:
    volumes = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            volumes.append(
                VolumeStats(
                    partition.device,
                    partition.mountpoint,
                    partition.fstype,
                    usage.total,
                    usage.used,
                    usage.free,
                    partition.opts,
                )
            )
        except (OSError, psutil.Error) as exc:
            volumes.append(
                VolumeStats(
                    partition.device,
                    partition.mountpoint,
                    partition.fstype,
                    None,
                    None,
                    None,
                    partition.opts,
                    str(exc),
                )
            )
    return tuple(volumes)
