"""Golden vectors for `backend/app/services/risk_models.py`.

Every case carries the raw hourly series as input, so the fixture pins the
whole chain - `summarise_days` and then the model - rather than only the model.
That matters because `summarise_days` is where the leaf-wetness proxy
(RH >= 90%) and the per-day aggregation live, and a port that gets the bucket
boundaries wrong would produce plausible-looking but wrong severity values.
"""
from __future__ import annotations

from datetime import timedelta

from app.services import risk_models as rm
from app.services.weather import HourPoint

from fixture_lib import BASE_DAY, _ts, day_hours, flat_hours, multi_day, to_jsonable

SOURCE = "backend/app/services/risk_models.py"


def _points(raw):
    """Rebuild HourPoint objects from the JSON-shaped series in the fixture."""
    from datetime import datetime

    return [
        HourPoint(
            ts=datetime.fromisoformat(p["ts"]),
            temp_c=p["temp_c"],
            humidity=p["humidity"],
            rainfall_mm=p["rainfall_mm"],
            is_forecast=p["is_forecast"],
        )
        for p in raw
    ]


def _wet_day(day, *, wet_hours: int, wet_temp: float, dry_temp: float, dry_rh: float = 55.0):
    """A day with an exact count of RH>=90 hours at an exact temperature, so
    the TOMCAST band a case lands in is unambiguous."""
    return flat_hours(_ts(day, 0), wet_hours, temp_c=wet_temp, humidity=95.0) + flat_hours(
        _ts(day, wet_hours), 24 - wet_hours, temp_c=dry_temp, humidity=dry_rh
    )


def _wet_series(specs):
    out = []
    for i, spec in enumerate(specs):
        out.extend(_wet_day(BASE_DAY + timedelta(days=i), **spec))
    return out


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------
QUALIFY = {"temp_min": 12.0, "temp_max": 19.0, "high_rh_hours": 14}
NO_QUALIFY_DRY = {"temp_min": 12.0, "temp_max": 19.0, "high_rh_hours": 4}
NO_QUALIFY_COLD = {"temp_min": 6.0, "temp_max": 14.0, "high_rh_hours": 14}

SCENARIOS = [
    (
        "smith_three_consecutive_qualifying_days",
        "Two consecutive qualifying days complete a Smith Period; a third extends the run.",
        multi_day([QUALIFY, QUALIFY, QUALIFY]),
        ["summarise_days", "smith_period", "beaumont_period", "tomcast_dsv"],
    ),
    (
        "smith_single_qualifying_day_near_miss",
        "One qualifying day scores 0.5 by the near-miss rule and must NOT trigger.",
        multi_day([NO_QUALIFY_DRY, QUALIFY, NO_QUALIFY_DRY]),
        ["summarise_days", "smith_period"],
    ),
    (
        "smith_broken_run_two_singles",
        "Two qualifying days separated by a dry day - the run resets, no period.",
        multi_day([QUALIFY, NO_QUALIFY_DRY, QUALIFY]),
        ["summarise_days", "smith_period"],
    ),
    (
        "smith_cold_but_humid",
        "Humidity threshold met but min temp below 10 C - the temperature gate must hold.",
        multi_day([NO_QUALIFY_COLD, NO_QUALIFY_COLD]),
        ["summarise_days", "smith_period"],
    ),
    (
        "smith_exact_threshold_boundary",
        "min temp exactly 10.0 and exactly 11 high-RH hours - both gates are >=, not >.",
        multi_day(
            [
                {"temp_min": 10.0, "temp_max": 18.0, "high_rh_hours": 11},
                {"temp_min": 10.0, "temp_max": 18.0, "high_rh_hours": 11},
            ]
        ),
        ["summarise_days", "smith_period"],
    ),
    (
        "beaumont_48h_continuous_run",
        "48 consecutive conducive hours clears the 46 h requirement.",
        flat_hours(_ts(BASE_DAY, 0), 48, temp_c=15.0, humidity=80.0),
        ["beaumont_period"],
    ),
    (
        "beaumont_45h_near_miss",
        "One hour short of the requirement - scores high but must not trigger.",
        flat_hours(_ts(BASE_DAY, 0), 45, temp_c=15.0, humidity=80.0),
        ["beaumont_period"],
    ),
    (
        "beaumont_run_broken_midway",
        "Two 30 h runs split by a single dry hour: the counter resets, it does not sum.",
        flat_hours(_ts(BASE_DAY, 0), 30, temp_c=15.0, humidity=80.0)
        + flat_hours(_ts(BASE_DAY, 0) + timedelta(hours=30), 1, temp_c=15.0, humidity=50.0)
        + flat_hours(_ts(BASE_DAY, 0) + timedelta(hours=31), 30, temp_c=15.0, humidity=80.0),
        ["beaumont_period"],
    ),
    (
        "tomcast_spray_threshold_reached",
        "Four days at 22 C with 21 wetness hours each = DSV 4/day, clearing the 15-DSV gate.",
        _wet_series([{"wet_hours": 21, "wet_temp": 22.0, "dry_temp": 26.0}] * 4),
        ["summarise_days", "tomcast_dsv"],
    ),
    (
        "tomcast_watch_band",
        "Accumulates into the 8-14 DSV watch band without reaching the spray threshold.",
        _wet_series([{"wet_hours": 13, "wet_temp": 22.0, "dry_temp": 26.0}] * 4),
        ["summarise_days", "tomcast_dsv"],
    ),
    (
        "tomcast_low_pressure",
        "Short wetness periods - severity stays near zero.",
        _wet_series([{"wet_hours": 2, "wet_temp": 22.0, "dry_temp": 26.0}] * 4),
        ["summarise_days", "tomcast_dsv"],
    ),
    (
        "tomcast_outside_temperature_bands",
        "Long wetness at 35 C falls outside every TOMCAST band and must score 0.",
        _wet_series([{"wet_hours": 22, "wet_temp": 35.0, "dry_temp": 36.0}] * 4),
        ["summarise_days", "tomcast_dsv"],
    ),
    (
        "tomcast_no_wetness_at_all",
        "Zero RH>=90 hours: wetness_mean_temp is null and DSV must be 0, not a crash.",
        _wet_series([{"wet_hours": 0, "wet_temp": 22.0, "dry_temp": 26.0}] * 3),
        ["summarise_days", "tomcast_dsv"],
    ),
    (
        "degree_days_short_warm_spell",
        "Six warm days - accumulates but does not complete a tuber moth generation.",
        multi_day([{"temp_min": 18.0, "temp_max": 32.0, "high_rh_hours": 6}] * 6),
        ["summarise_days", "degree_days:potato_tuber_moth", "degree_days:aphid_vector"],
    ),
    (
        "degree_days_generation_complete",
        "Twenty-five warm days completes a tuber moth generation - the emergence peak.",
        multi_day([{"temp_min": 18.0, "temp_max": 32.0, "high_rh_hours": 6}] * 25),
        ["degree_days:potato_tuber_moth"],
    ),
    (
        "degree_days_below_base_temperature",
        "Max temp under the 10 C base: accumulation must be exactly 0, never negative.",
        multi_day([{"temp_min": 3.0, "temp_max": 8.0, "high_rh_hours": 6}] * 6),
        ["summarise_days", "degree_days:potato_tuber_moth"],
    ),
    (
        "degree_days_above_upper_cutoff",
        "Max temp above the 35 C cut-off must be clamped, not counted in full.",
        multi_day([{"temp_min": 28.0, "temp_max": 44.0, "high_rh_hours": 6}] * 6),
        ["degree_days:potato_tuber_moth"],
    ),
    (
        "single_hour_series",
        "Degenerate input: one hour. Every model must return a shape, not raise.",
        flat_hours(_ts(BASE_DAY, 9), 1, temp_c=15.0, humidity=80.0),
        ["summarise_days", "smith_period", "beaumont_period", "tomcast_dsv"],
    ),
    (
        "empty_series",
        "Degenerate input: no hours at all - the offline path hits this before any sync.",
        [],
        ["summarise_days", "smith_period", "beaumont_period", "tomcast_dsv"],
    ),
]


def _run(fn: str, raw_points):
    pts = _points(raw_points)
    days = rm.summarise_days(pts)
    if fn == "summarise_days":
        return {"days": to_jsonable(days)}
    if fn == "smith_period":
        return to_jsonable(rm.smith_period(days))
    if fn == "beaumont_period":
        return to_jsonable(rm.beaumont_period(pts))
    if fn == "tomcast_dsv":
        return to_jsonable(rm.tomcast_dsv(days))
    if fn.startswith("degree_days:"):
        pest = rm.PEST_MODELS[fn.split(":", 1)[1]]
        return to_jsonable(rm.degree_days(days, pest))
    raise ValueError(f"unknown fn {fn}")


def build() -> dict:
    cases = []
    for name, why, series, fns in SCENARIOS:
        for fn in fns:
            cases.append(
                {
                    "id": f"{name}::{fn}",
                    "why": why,
                    "fn": fn,
                    "input": {"hours": series},
                    "expect": _run(fn, series),
                }
            )
    return {
        "suite": "risk_models",
        "source": SOURCE,
        "description": (
            "Published agronomic models. Input is the raw hourly series, so the "
            "summarise_days aggregation is pinned alongside each model."
        ),
        "constants": {
            "smith_min_temp_c": rm.SMITH_MIN_TEMP_C,
            "smith_rh_pct": rm.SMITH_RH_PCT,
            "smith_rh_hours": rm.SMITH_RH_HOURS,
            "smith_consecutive_days": rm.SMITH_CONSECUTIVE_DAYS,
            "beaumont_min_temp_c": rm.BEAUMONT_MIN_TEMP_C,
            "beaumont_rh_pct": rm.BEAUMONT_RH_PCT,
            "beaumont_hours": rm.BEAUMONT_HOURS,
            "leaf_wetness_rh_pct": rm.LEAF_WETNESS_RH_PCT,
            "tomcast_table": [[lo, hi, cuts] for lo, hi, cuts in rm.TOMCAST_TABLE],
            "early_blight_dsv_spray_threshold": rm.EARLY_BLIGHT_DSV_SPRAY_THRESHOLD,
            "early_blight_dsv_watch_threshold": rm.EARLY_BLIGHT_DSV_WATCH_THRESHOLD,
            "pest_models": {
                k: {
                    "base_temp_c": v.base_temp_c,
                    "upper_temp_c": v.upper_temp_c,
                    "degree_days_per_generation": v.degree_days_per_generation,
                }
                for k, v in rm.PEST_MODELS.items()
            },
        },
        "cases": cases,
    }
