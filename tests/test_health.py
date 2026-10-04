from dataclasses import replace

from pulse.core.processes import ProcessSnapshot, ProcessStats
from pulse.core.system import BatteryStats, SystemStats
from pulse.health.engine import analyze_health
from pulse.health.models import OverallStatus, Severity
from pulse.optimization.engine import recommend_maintenance

BASE = SystemStats("Darwin", 10, 1, 10, 10, 1, 100, 10, 100)


def test_real_available_disk_space_overrides_misleading_used_percent() -> None:
    report = analyze_health(replace(BASE, disk_free=4))
    assert report.status == OverallStatus.critical
    assert report.issues[0].id == "disk_critical"
    assert report.issues[0].evidence["available_percent"] == 4


def test_memory_usage_is_informational_not_pressure_claim() -> None:
    report = analyze_health(replace(BASE, memory_percent=90))
    assert report.status == OverallStatus.no_alerts
    assert report.issues[0].severity == Severity.info
    assert "does not prove memory pressure" in report.issues[0].description


def test_swap_and_low_charge_are_separate_observations() -> None:
    report = analyze_health(
        replace(BASE, swap_used=2 * 1024**3, battery=BatteryStats(10, False, None))
    )
    assert {issue.id for issue in report.issues} == {"swap_in_use", "battery_low"}
    plugged = analyze_health(replace(BASE, battery=BatteryStats(10, True, None)))
    assert not plugged.issues


def test_heavy_process_evidence_and_incomplete_coverage() -> None:
    report = analyze_health(BASE, ProcessSnapshot((ProcessStats(42, "app", 110, 1),), 2))
    assert report.issues[0].evidence["pid"] == 42
    assert "2 processes" in report.limitations[-1]
    assert all(not r.automatic for r in recommend_maintenance(report))


def test_no_fake_optimization_when_quiet() -> None:
    assert recommend_maintenance(analyze_health(BASE)) == ()


def test_storage_severity_boundaries() -> None:
    for free, expected in (
        (11, None),
        (10, Severity.warning),
        (6, Severity.warning),
        (5, Severity.critical),
        (0, Severity.critical),
    ):
        report = analyze_health(replace(BASE, disk_free=free))
        assert (
            [i.severity for i in report.issues] == []
            if expected is None
            else [i.severity for i in report.issues] == [expected]
        )
