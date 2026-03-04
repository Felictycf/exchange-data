from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() != "":
        try:
            return float(value)
        except ValueError:
            return None
    return None


def ms_to_iso8601(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    # Lighter uses both seconds and milliseconds in different endpoints.
    if ts < 10_000_000_000:
        ts = ts * 1000
    dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
    return dt.isoformat().replace("+00:00", "Z")


def now_iso8601() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
