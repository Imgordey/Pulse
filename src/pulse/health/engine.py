"""Deterministic snapshot rules; no score and no storage traversal."""

from pulse.core.processes import ProcessSnapshot
from pulse.core.system import SystemStats
from pulse.health.models import HealthReport, Issue, OverallStatus, Severity

GIB = 1024**3


def analyze_health(stats: SystemStats, processes: ProcessSnapshot | None = None) -> HealthReport:
    issues: list[Issue] = []
    if stats.cpu_percent >= 85:
        issues.append(
            Issue(
                "cpu_high",
                "CPU",
                Severity.warning,
                "Your Mac is busy",
                "High CPU usage during this sample; a short burst can be normal.",
                {"cpu_percent": stats.cpu_percent, "sample_seconds": 0.5},
                "Run pulse processes --sort cpu; repeat after the current task finishes.",
            )
        )
    if stats.memory_percent >= 85:
        issues.append(
            Issue(
                "memory_high",
                "Memory",
                Severity.info,
                "Much of your memory is in use",
                "High reported memory usage; this alone does not prove memory pressure.",
                {"memory_percent": stats.memory_percent},
                "Run pulse processes --sort memory and check Memory Pressure in Activity Monitor.",
            )
        )
    if stats.swap_used >= 2 * GIB:
        issues.append(
            Issue(
                "swap_in_use",
                "Memory",
                Severity.info,
                "Your Mac is using disk-backed memory",
                "Swap is in use; this sample cannot tell whether swapping is slowing apps.",
                {"swap_used_bytes": stats.swap_used},
                "If apps feel slow, check Memory Pressure and close unused apps normally.",
            )
        )
    used_percent = stats.disk_percent
    if stats.disk_free is not None and stats.disk_total > 0:
        used_percent = 100 * (1 - stats.disk_free / stats.disk_total)
    if used_percent >= 90:
        issues.append(
            Issue(
                "disk_critical" if used_percent >= 95 else "disk_low_space",
                "Disk",
                Severity.critical if used_percent >= 95 else Severity.warning,
                "Storage is running low",
                "The system disk has little available space.",
                {"available_percent": round(100 - used_percent, 2)},
                "Review macOS Storage settings and pulse scan before removing files.",
            )
        )
    if stats.battery is not None and not stats.battery.plugged_in and stats.battery.percent <= 10:
        issues.append(
            Issue(
                "battery_low",
                "Battery",
                Severity.warning,
                "Battery charge is low",
                "Connect your Mac to power soon. Charge does not indicate battery condition.",
                {"charge_percent": stats.battery.percent},
                "Connect your charger.",
            )
        )
    if processes is not None:
        for process in processes.processes:
            cpu_high = process.cpu_percent >= 100
            memory_high = stats.memory_total > 0 and process.memory_rss >= stats.memory_total / 4
            if cpu_high or memory_high:
                issues.append(
                    Issue(
                        f"process_heavy_{process.pid}",
                        "Processes",
                        Severity.info,
                        f"{process.name} is using substantial resources",
                        "A busy app may be doing useful work; one sample cannot prove a problem.",
                        {
                            "pid": process.pid,
                            "cpu_percent": process.cpu_percent,
                            "resident_bytes": process.memory_rss,
                        },
                        "Review the app in Activity Monitor. Save work before closing it normally.",
                    )
                )
    status = OverallStatus.no_alerts
    if any(i.severity == Severity.warning for i in issues):
        status = OverallStatus.attention
    if any(i.severity == Severity.critical for i in issues):
        status = OverallStatus.critical
    limitations = [
        "One sample is not a full health assessment.",
        "macOS Memory Pressure and battery condition are not measured.",
    ]
    if processes is not None and processes.skipped:
        limitations.append(f"{processes.skipped} processes were inaccessible or exited.")
    return HealthReport(tuple(issues), status, tuple(limitations))
