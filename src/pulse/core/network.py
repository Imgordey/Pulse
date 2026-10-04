"""Network counters and explicitly sampled rates; no packet inspection."""

import time
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class NetworkTotals:
    bytes_sent: int
    bytes_received: int
    sampled_at: float


@dataclass(frozen=True)
class NetworkActivity:
    sent_per_second: float | None
    received_per_second: float | None
    reason: str | None = None


def get_network_totals() -> NetworkTotals | None:
    try:
        counters = psutil.net_io_counters()
        if counters is None:
            return None
        return NetworkTotals(counters.bytes_sent, counters.bytes_recv, time.monotonic())
    except (OSError, psutil.Error):
        return None


def network_activity(before: NetworkTotals, after: NetworkTotals) -> NetworkActivity:
    elapsed = after.sampled_at - before.sampled_at
    sent = after.bytes_sent - before.bytes_sent
    received = after.bytes_received - before.bytes_received
    if elapsed <= 0 or sent < 0 or received < 0:
        return NetworkActivity(None, None, "Counters reset or sample times are invalid")
    return NetworkActivity(sent / elapsed, received / elapsed)
