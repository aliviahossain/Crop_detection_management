"""Shared helpers for building and comparing golden-vector fixtures.

The fixtures pin the *behaviour* of the Python domain services so a second
implementation (Dart, on the handset) can be held to the same numbers. See
`mobileapp/fixtures/FORMAT.md` for the contract.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone

# Keys whose values are human prose. A mismatch here is a WARNING (someone
# copy-edited a message), not a FAILURE (someone changed a decision). Without
# this split the suite becomes the thing people disable after a wording tweak.
PROSE_KEYS = {"explanation", "message", "action", "note", "display", "why"}

# Floats are compared to this tolerance so a language's last-bit rounding does
# not fail a suite. Everything in these services rounds to <= 3 dp anyway.
FLOAT_TOL = 1e-6


def to_jsonable(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, float):
        # Normalise -0.0 and keep JSON round-trip stable.
        return obj + 0.0
    return obj


def compare(expected, actual, path="", hard=None, soft=None):
    """Walk two JSON trees. Returns (hard_diffs, soft_diffs)."""
    hard = [] if hard is None else hard
    soft = [] if soft is None else soft
    leaf_key = path.rsplit(".", 1)[-1].split("[")[0]
    bucket = soft if leaf_key in PROSE_KEYS else hard

    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in sorted(set(expected) | set(actual)):
            if k not in expected:
                hard.append(f"{path}.{k}: unexpected key (actual={actual[k]!r})")
            elif k not in actual:
                hard.append(f"{path}.{k}: missing key (expected={expected[k]!r})")
            else:
                compare(expected[k], actual[k], f"{path}.{k}", hard, soft)
        return hard, soft

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            hard.append(f"{path}: length {len(expected)} != {len(actual)}")
            return hard, soft
        for i, (e, a) in enumerate(zip(expected, actual)):
            compare(e, a, f"{path}[{i}]", hard, soft)
        return hard, soft

    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected != actual:
            bucket.append(f"{path}: {expected!r} != {actual!r}")
        return hard, soft

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if not math.isclose(float(expected), float(actual), rel_tol=0, abs_tol=FLOAT_TOL):
            bucket.append(f"{path}: {expected!r} != {actual!r}")
        return hard, soft

    if expected != actual:
        bucket.append(f"{path}: {expected!r} != {actual!r}")
    return hard, soft


# ----------------------------------------------------------------------
# Deterministic weather-series builders.
#
# Fixtures must be reproducible byte-for-byte, so nothing here touches a
# clock, a random source, or the network.
# ----------------------------------------------------------------------
BASE_DAY = date(2026, 1, 12)


def _ts(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def day_hours(
    day: date,
    *,
    temp_min: float,
    temp_max: float,
    high_rh_hours: int,
    rh_high: float = 95.0,
    rh_low: float = 60.0,
    rain_mm: float = 0.0,
):
    """24 hourly points with an exact min/max and an exact count of hours at
    `rh_high`. Cosine temperature curve: coldest at 05:00, warmest at 17:00,
    which is what the agronomic models assume about a field day."""
    mid = (temp_min + temp_max) / 2.0
    amp = (temp_max - temp_min) / 2.0
    out = []
    for h in range(24):
        temp = mid - amp * math.cos(2 * math.pi * (h - 5) / 24.0)
        # Pin the exact extremes so temp_min/temp_max are not curve artefacts.
        if h == 5:
            temp = temp_min
        elif h == 17:
            temp = temp_max
        out.append(
            {
                "ts": _ts(day, h).isoformat(),
                "temp_c": round(temp, 2),
                "humidity": rh_high if h < high_rh_hours else rh_low,
                "rainfall_mm": round(rain_mm / 24.0, 3),
                "is_forecast": False,
            }
        )
    return out


def flat_hours(start: datetime, hours: int, *, temp_c: float, humidity: float, rain_mm: float = 0.0):
    """A run of identical hours - used to build exact Beaumont run lengths,
    which are an hour-level property and cannot be expressed per-day."""
    return [
        {
            "ts": (start + timedelta(hours=i)).isoformat(),
            "temp_c": temp_c,
            "humidity": humidity,
            "rainfall_mm": rain_mm,
            "is_forecast": False,
        }
        for i in range(hours)
    ]


def multi_day(specs):
    """specs: list of dicts accepted by day_hours, applied to consecutive days
    starting at BASE_DAY."""
    points = []
    for i, spec in enumerate(specs):
        points.extend(day_hours(BASE_DAY + timedelta(days=i), **spec))
    return points


def write_suite(path, suite: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
