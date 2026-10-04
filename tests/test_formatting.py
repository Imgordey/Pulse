import pytest

from pulse.cli import _gib, _uptime


@pytest.mark.parametrize(
    "value,expected", [(0, "0.0 GiB"), (1024**3, "1.0 GiB"), (1536 * 1024**2, "1.5 GiB")]
)
def test_gib(value: int, expected: str) -> None:
    assert _gib(value) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0d 0h 0m"), (59, "0d 0h 0m"), (60, "0d 0h 1m"), (86400, "1d 0h 0m"), (90060, "1d 1h 1m")],
)
def test_uptime(seconds: int, expected: str) -> None:
    assert _uptime(seconds) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(0, "0.0 B"), (512, "512.0 B"), (1024, "1.0 KiB"), (1024**2, "1.0 MiB"), (1024**3, "1.0 GiB")],
)
def test_size(value: int, expected: str) -> None:
    from pulse.cli import _size

    assert _size(value) == expected
