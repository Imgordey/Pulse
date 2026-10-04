"""Compatibility entry point for the original resource observations."""

from pulse.core.system import SystemStats
from pulse.health.engine import analyze_health
from pulse.health.models import Issue


def assess_system(stats: SystemStats) -> list[Issue]:
    return list(analyze_health(stats).issues)
