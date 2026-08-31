"""Published agronomic risk models -- the *primary* forecasting layer.

Section 4 of the brief is explicit about this: there is no ready-made labelled
dataset linking weather + crop stage + variety + soil + pest history to actual
outbreak events for Indian crops, so "train XGBoost on it" cannot be the
foundation. These are deterministic, validated, decades-old formulas that run
today with nothing but a weather series.

Implemented here:

* **Smith Period** (Smith, 1956; UK MAFF criteria) -- late blight
  (*Phytophthora infestans*). Two consecutive days each with min temp >= 10 C
  and >= 11 hours at RH >= 90%.
* **Beaumont Period** (Beaumont, 1947) -- a wider, earlier-warning late blight
  criterion: 46 consecutive hours at temp >= 10 C and RH >= 75%.
* **TOMCAST DSV** (Pitblado; Madden/Pennypacker severity values) -- early
  blight (*Alternaria solani*). Daily severity 0-4 from leaf-wetness hours and
  mean temperature during wetness; accumulate and spray near threshold.
* **Growing degree-days** (single-triangle, base-temperature method) -- pest
  emergence timing, e.g. potato tuber moth.

Leaf wetness is proxied by RH >= 90%, the standard substitute when no leaf
wetness sensor is present. Where a pest trap *is* reporting (see
`sensor_readings`), the risk engine layers observed counts on top.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from app.services.weather import HourPoint

# ----------------------------------------------------------------------
# Thresholds (single source of truth; the XGBoost layer reweights these)
# ----------------------------------------------------------------------
SMITH_MIN_TEMP_C = 10.0
SMITH_RH_PCT = 90.0
SMITH_RH_HOURS = 11
SMITH_CONSECUTIVE_DAYS = 2

BEAUMONT_MIN_TEMP_C = 10.0
BEAUMONT_RH_PCT = 75.0
BEAUMONT_HOURS = 46

LEAF_WETNESS_RH_PCT = 90.0

# TOMCAST: (temp_lo, temp_hi, [wetness-hour cut points]) -> severity index
# Severity = number of cut points the wetness hours meet or exceed.
TOMCAST_TABLE: list[tuple[float, float, list[int]]] = [
    (13.0, 17.9, [7, 16, 21]),
    (18.0, 20.9, [4, 9, 16, 23]),
    (21.0, 25.9, [3, 6, 13, 21]),
    (26.0, 29.9, [4, 9, 16, 23]),
]
EARLY_BLIGHT_DSV_SPRAY_THRESHOLD = 15
EARLY_BLIGHT_DSV_WATCH_THRESHOLD = 8


@dataclass
class DaySummary:
    day: date
    temp_min: float
    temp_max: float
    temp_mean: float
    rh_mean: float
    hours_rh_above_90: int
    hours_rh_above_75: int
    wetness_hours: int
    wetness_mean_temp: float | None
    rainfall_mm: float


@dataclass
class ModelOutput:
    name: str
    triggered: bool
    score: float  # 0-1, comparable across models
    detail: dict = field(default_factory=dict)
    explanation: str = ""


def summarise_days(points: list[HourPoint]) -> list[DaySummary]:
    """Collapse an hourly series into the per-day aggregates the models need."""
    buckets: dict[date, list[HourPoint]] = defaultdict(list)
    for p in points:
        buckets[p.ts.date()].append(p)

    out: list[DaySummary] = []
    for day in sorted(buckets):
        hrs = buckets[day]
        temps = [h.temp_c for h in hrs]
        hums = [h.humidity for h in hrs]
        wet = [h for h in hrs if h.humidity >= LEAF_WETNESS_RH_PCT]
        out.append(
            DaySummary(
                day=day,
                temp_min=round(min(temps), 1),
                temp_max=round(max(temps), 1),
                temp_mean=round(sum(temps) / len(temps), 1),
                rh_mean=round(sum(hums) / len(hums), 1),
                hours_rh_above_90=len(wet),
                hours_rh_above_75=sum(1 for h in hrs if h.humidity >= BEAUMONT_RH_PCT),
                wetness_hours=len(wet),
                wetness_mean_temp=(
                    round(sum(h.temp_c for h in wet) / len(wet), 1) if wet else None
                ),
                rainfall_mm=round(sum(h.rainfall_mm for h in hrs), 1),
            )
        )
    return out


# ----------------------------------------------------------------------
# Late blight
# ----------------------------------------------------------------------
def smith_period(days: list[DaySummary]) -> ModelOutput:
    """A Smith Period = `SMITH_CONSECUTIVE_DAYS` consecutive qualifying days.

    A qualifying day has min temp >= 10 C and >= 11 hours at RH >= 90%.
    Two in a row means blight infection conditions have been met and a
    protectant spray decision is due.
    """
    qualifying = [
        d.temp_min >= SMITH_MIN_TEMP_C and d.hours_rh_above_90 >= SMITH_RH_HOURS for d in days
    ]
    periods: list[dict] = []
    run = 0
    best_run = 0
    for idx, ok in enumerate(qualifying):
        run = run + 1 if ok else 0
        best_run = max(best_run, run)
        if run >= SMITH_CONSECUTIVE_DAYS:
            window = days[idx - run + 1 : idx + 1]
            periods.append(
                {
                    "start": window[0].day.isoformat(),
                    "end": window[-1].day.isoformat(),
                    "days": run,
                }
            )
    # A "near miss" still matters agronomically -- one qualifying day is a warning.
    score = min(1.0, best_run / SMITH_CONSECUTIVE_DAYS) if best_run else 0.0
    if not periods and best_run == 1:
        score = 0.5

    triggered = bool(periods)
    if triggered:
        last = periods[-1]
        explanation = (
            f"Smith Period met: {last['days']} consecutive days "
            f"({last['start']} to {last['end']}) with minimum temperature >= "
            f"{SMITH_MIN_TEMP_C} C and at least {SMITH_RH_HOURS} hours at RH >= {SMITH_RH_PCT}%. "
            "These are late blight infection conditions."
        )
    elif best_run == 1:
        explanation = (
            "One qualifying day recorded (min temp and humidity thresholds met). "
            f"A second consecutive day would complete a Smith Period."
        )
    else:
        explanation = "No day met both the temperature and humidity-duration thresholds."

    return ModelOutput(
        name="smith_period",
        triggered=triggered,
        score=round(score, 3),
        detail={
            "periods": periods,
            "longest_run_days": best_run,
            "qualifying_days": [
                d.day.isoformat() for d, ok in zip(days, qualifying) if ok
            ],
            "thresholds": {
                "min_temp_c": SMITH_MIN_TEMP_C,
                "rh_pct": SMITH_RH_PCT,
                "rh_hours": SMITH_RH_HOURS,
                "consecutive_days": SMITH_CONSECUTIVE_DAYS,
            },
        },
        explanation=explanation,
    )


def beaumont_period(points: list[HourPoint]) -> ModelOutput:
    """46 consecutive hours at >= 10 C and RH >= 75%. Fires earlier and more
    often than Smith -- used as the amber pre-warning."""
    best = 0
    run = 0
    start_ts: datetime | None = None
    best_start: datetime | None = None
    for p in points:
        if p.temp_c >= BEAUMONT_MIN_TEMP_C and p.humidity >= BEAUMONT_RH_PCT:
            if run == 0:
                start_ts = p.ts
            run += 1
            if run > best:
                best, best_start = run, start_ts
        else:
            run = 0
    triggered = best >= BEAUMONT_HOURS
    return ModelOutput(
        name="beaumont_period",
        triggered=triggered,
        score=round(min(1.0, best / BEAUMONT_HOURS), 3),
        detail={
            "longest_run_hours": best,
            "required_hours": BEAUMONT_HOURS,
            "run_started": best_start.isoformat() if best_start else None,
        },
        explanation=(
            f"Beaumont Period met: {best} consecutive hours above {BEAUMONT_MIN_TEMP_C} C "
            f"with RH >= {BEAUMONT_RH_PCT}%."
            if triggered
            else f"Longest conducive run was {best}h of the {BEAUMONT_HOURS}h required."
        ),
    )


# ----------------------------------------------------------------------
# Early blight
# ----------------------------------------------------------------------
def _dsv_for_day(d: DaySummary) -> int:
    """TOMCAST daily disease severity value, 0-4."""
    if d.wetness_hours == 0 or d.wetness_mean_temp is None:
        return 0
    t = d.wetness_mean_temp
    for lo, hi, cuts in TOMCAST_TABLE:
        if lo <= t <= hi:
            return sum(1 for c in cuts if d.wetness_hours >= c)
    return 0  # outside 13-30 C: sporulation is negligible


def tomcast_dsv(days: list[DaySummary]) -> ModelOutput:
    per_day = [{"day": d.day.isoformat(), "dsv": _dsv_for_day(d)} for d in days]
    total = sum(x["dsv"] for x in per_day)
    triggered = total >= EARLY_BLIGHT_DSV_SPRAY_THRESHOLD
    score = min(1.0, total / EARLY_BLIGHT_DSV_SPRAY_THRESHOLD)
    if triggered:
        explanation = (
            f"Accumulated {total} disease severity values (DSV) over {len(days)} days, "
            f"at or above the {EARLY_BLIGHT_DSV_SPRAY_THRESHOLD}-DSV early blight spray "
            "threshold."
        )
    elif total >= EARLY_BLIGHT_DSV_WATCH_THRESHOLD:
        explanation = (
            f"Accumulated {total} DSV - approaching the "
            f"{EARLY_BLIGHT_DSV_SPRAY_THRESHOLD}-DSV spray threshold. Scout fields now."
        )
    else:
        explanation = f"Accumulated {total} DSV - early blight pressure is low."
    return ModelOutput(
        name="tomcast_dsv",
        triggered=triggered,
        score=round(score, 3),
        detail={
            "total_dsv": total,
            "spray_threshold": EARLY_BLIGHT_DSV_SPRAY_THRESHOLD,
            "watch_threshold": EARLY_BLIGHT_DSV_WATCH_THRESHOLD,
            "per_day": per_day,
        },
        explanation=explanation,
    )


# ----------------------------------------------------------------------
# Pest emergence
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class PestModel:
    key: str
    display: str
    base_temp_c: float
    upper_temp_c: float
    degree_days_per_generation: float
    note: str


PEST_MODELS: dict[str, PestModel] = {
    "potato_tuber_moth": PestModel(
        key="potato_tuber_moth",
        display="Potato tuber moth (Phthorimaea operculella)",
        base_temp_c=10.0,
        upper_temp_c=35.0,
        degree_days_per_generation=360.0,
        note=(
            "The major storage and field pest of potato in Maharashtra. Around 360 "
            "degree-days above 10 C completes a generation; time pheromone-trap checks "
            "and any intervention to the emergence peak."
        ),
    ),
    "aphid_vector": PestModel(
        key="aphid_vector",
        display="Aphid complex (virus vectors)",
        base_temp_c=4.4,
        upper_temp_c=30.0,
        degree_days_per_generation=120.0,
        note=(
            "Aphids matter mainly as virus vectors in seed potato. Degree-day "
            "accumulation indicates flight activity build-up."
        ),
    ),
}


def degree_days(days: list[DaySummary], pest: PestModel) -> ModelOutput:
    """Single-triangle degree-day accumulation with an upper cut-off."""
    total = 0.0
    series: list[dict] = []
    for d in days:
        t_max = min(d.temp_max, pest.upper_temp_c)
        t_min = max(d.temp_min, pest.base_temp_c)
        dd = max(0.0, (t_max + t_min) / 2 - pest.base_temp_c) if t_max > pest.base_temp_c else 0.0
        total += dd
        series.append({"day": d.day.isoformat(), "dd": round(dd, 1)})
    generations = total / pest.degree_days_per_generation
    triggered = generations >= 1.0
    return ModelOutput(
        name=f"degree_days:{pest.key}",
        triggered=triggered,
        score=round(min(1.0, generations), 3),
        detail={
            "pest": pest.key,
            "display": pest.display,
            "accumulated_dd": round(total, 1),
            "dd_per_generation": pest.degree_days_per_generation,
            "generations": round(generations, 2),
            "base_temp_c": pest.base_temp_c,
            "per_day": series,
            "note": pest.note,
        },
        explanation=(
            f"{round(total, 1)} degree-days accumulated above {pest.base_temp_c} C "
            f"({round(generations, 2)} of a generation). "
            + (
                "A generation is complete - expect an emergence peak and check traps."
                if triggered
                else "Emergence peak has not been reached yet."
            )
        ),
    )
