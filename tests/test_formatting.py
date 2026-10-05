import pytest

from pulse.cli import _gb, _uptime


@pytest.mark.parametrize(
    "value,expected", [(0, "0.0 GB"), (1_000_000_000, "1.0 GB"), (1_500_000_000, "1.5 GB")]
)
def test_gb(value: int, expected: str) -> None:
    assert _gb(value) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0d 0h 0m"), (59, "0d 0h 0m"), (60, "0d 0h 1m"), (86400, "1d 0h 0m"), (90060, "1d 1h 1m")],
)
def test_uptime(seconds: int, expected: str) -> None:
    assert _uptime(seconds) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(0, "0.0 B"), (999, "999.0 B"), (1000, "1.0 KB"), (1_500_000, "1.5 MB"), (1024**3, "1.1 GB")],
)
def test_size(value: int, expected: str) -> None:
    from pulse.cli import _size

    assert _size(value) == expected
