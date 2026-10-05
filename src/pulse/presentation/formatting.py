"""Decimal storage units shared by CLI and desktop: 1 MB = 1,000,000 bytes."""


def format_size(value: int) -> str:
    if value < 0:
        raise ValueError("A byte count cannot be negative")
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB", "EB"):
        if number < 1000 or unit == "EB":
            return f"{number:.1f} {unit}"
        number /= 1000
    raise AssertionError("Unreachable")


def format_gb(value: int) -> str:
    return f"{value / 1_000_000_000:.1f} GB"
