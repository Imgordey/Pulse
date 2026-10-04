from dataclasses import replace

import pytest

from pulse.core.diagnostics import assess_system
from pulse.core.system import SystemStats

BASE = SystemStats("Darwin", 10, 1, 10, 10, 1, 10, 10, 100)


def test_quiet_snapshot():
    assert assess_system(BASE) == []


@pytest.mark.parametrize(
    "field,threshold,resource",
    [
        ("cpu_percent", 85, "CPU"),
        ("memory_percent", 85, "Memory"),
        ("disk_percent", 90, "Disk"),
    ],
)
def test_threshold_boundaries(field, threshold, resource):
    assert assess_system(replace(BASE, **{field: threshold - 0.1})) == []
    findings = assess_system(replace(BASE, **{field: threshold}))
    assert [f.resource for f in findings] == [resource]
    assert findings[0].suggestion
