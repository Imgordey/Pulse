"""Snapshot-based observations, not a diagnosis of macOS memory pressure."""

from dataclasses import dataclass

from pulse.core.system import SystemStats


@dataclass(frozen=True)
class Finding:
    resource: str
    message: str
    suggestion: str


def assess_system(stats: SystemStats) -> list[Finding]:
    findings = []
    if stats.cpu_percent >= 85:
        findings.append(
            Finding(
                "CPU",
                "High CPU usage during this sample.",
                "Run pulse processes --sort cpu; repeat after the current task finishes.",
            )
        )
    if stats.memory_percent >= 85:
        findings.append(
            Finding(
                "Memory",
                "High reported memory usage; this alone does not prove memory pressure.",
                "Run pulse processes --sort memory and check Memory Pressure in Activity Monitor.",
            )
        )
    if stats.disk_percent >= 90:
        findings.append(
            Finding(
                "Disk",
                "The root filesystem reports little free space.",
                "Review Storage in macOS System Settings before removing files manually.",
            )
        )
    return findings
