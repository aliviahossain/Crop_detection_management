"""Generate the synthetic dataset the phone ships with.

The officer screens -- dashboard, hotspot map, review queue -- are meaningless
against an empty database, and a handset has no other farmers' cases until it
syncs. Without this the phone shows a technically-correct wall of zeros, which
in a demo reads as "broken" and in the field reads as "no disease anywhere".

Two decisions worth stating, because both are visible in the output format:

**Offsets, not timestamps.** Every record carries `day_offset`/`hour` instead
of an absolute datetime, and the app materialises them against the current
date at read time. A fixed timestamp would mean an APK built today shows a
dashboard full of month-old cases in three months, with an empty "last 7 days"
window -- stale in exactly the way that makes a demo look dead.

**Raw records, not precomputed aggregates.** The app derives the summary, the
trend series and the hotspot cells from these rows. That costs some Dart, and
buys a demo where the period selector and the district filter actually do
something, instead of four numbers that never move.

This is a sibling of `scripts/seed_demo_data.py`, not a replacement: that one
seeds the server's SQLite for the web app, this one produces a read-only asset
for the handset. They share constants and intent, but neither reads the other's
output and there is no reason for the two bodies of demo data to be identical.

    python mobileapp/tools/export_demo_dataset.py --write
    python mobileapp/tools/export_demo_dataset.py --check
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "mobileapp" / "app" / "assets" / "demo" / "dataset.json"

# Imported rather than restated, so a new district or variety reaches the phone
# and the server together.
from seed_demo_data import (  # noqa: E402
    CLASS_WEIGHTS,
    LOCATIONS,
    REVIEWERS,
    SOILS,
    STAGES,
    VARIETIES,
    weighted_choice,
)

from app.services.geo import geo_cell  # noqa: E402

FOLLOW_UP_OUTCOMES = [
    ("resolved", 0.45),
    ("improving", 0.30),
    ("unchanged", 0.17),
    ("worsened", 0.08),
]


def build(cases: int, days: int, traps: int, seed: int) -> dict:
    rng = random.Random(seed)
    out_cases = []
    out_follow_ups = []

    for i in range(cases):
        district, village, lat0, lon0 = rng.choice(LOCATIONS)
        # Jitter within roughly 5 km so cases cluster into cells rather than
        # landing on one point.
        lat = lat0 + rng.uniform(-0.045, 0.045)
        lon = lon0 + rng.uniform(-0.045, 0.045)
        cls = weighted_choice(rng, CLASS_WEIGHTS)
        confidence = round(rng.uniform(0.42, 0.97), 3)
        day_offset = rng.randint(0, days)
        hour = rng.randint(0, 23)

        if cls == "potato_healthy":
            risk_level, risk_score = "low", round(rng.uniform(0.05, 0.35), 3)
        elif cls == "potato_late_blight":
            risk_level = "high" if rng.random() < 0.6 else "medium"
            risk_score = round(rng.uniform(0.45, 0.95), 3)
        else:
            risk_level, risk_score = "medium", round(rng.uniform(0.3, 0.7), 3)

        low_conf = confidence < 0.55
        case_id = i + 1
        case = {
            "id": case_id,
            "day_offset": day_offset,
            "hour": hour,
            "source": "image" if rng.random() < 0.8 else "risk_forecast",
            "farmer_name": "Demo Farmer %03d" % case_id,
            "crop": "potato",
            "variety": rng.choice(VARIETIES),
            "crop_stage": rng.choice(STAGES),
            "soil_condition": rng.choice(SOILS),
            "district": district,
            "village": village,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "geo_cell": geo_cell(lat, lon),
            "predicted_class": cls,
            "confidence": confidence,
            "model_version": "demo-seed",
            "risk_level": risk_level,
            "risk_score": risk_score,
            "escalate": low_conf or risk_level == "high",
            "escalation_reasons": [
                {
                    "code": "low_confidence" if low_conf else "fast_moving_disease",
                    "message": "Seeded demo case.",
                    "action": "Confirm with an extension officer.",
                }
            ],
            "language": rng.choice(["mr", "mr", "en", "hi"]),
            "review_status": "pending",
            "confirmed_class": None,
            "reviewer": None,
            "reviewer_notes": None,
            "reviewed_after_days": None,
        }

        # About 55% get reviewed -- a realistic backlog for the review queue,
        # and the reason the queue is not either empty or exhaustively done.
        if rng.random() < 0.55:
            if rng.random() < 0.78:
                case["review_status"] = "confirmed"
                case["confirmed_class"] = cls
            else:
                case["review_status"] = "corrected"
                others = [c for c, _ in CLASS_WEIGHTS if c != cls]
                case["confirmed_class"] = rng.choice(others)
            case["reviewer"] = rng.choice(REVIEWERS)
            case["reviewed_after_days"] = rng.randint(1, 3)
            case["reviewer_notes"] = "Field inspection completed."

        out_cases.append(case)

        follow_up = {
            "id": case_id,
            "case_id": case_id,
            "day_offset": day_offset,
            "due_after_days": 7,
            "notes": "Seeded demo follow-up.",
            "outcome": "pending",
            "treatment_applied": None,
            "closed_after_days": None,
        }
        # Only a follow-up whose due date has already passed can have an
        # outcome; the rest are legitimately still open.
        if day_offset > 7 and rng.random() < 0.7:
            follow_up["outcome"] = weighted_choice(rng, FOLLOW_UP_OUTCOMES)
            follow_up["treatment_applied"] = "Mancozeb 75% WP @ 2.5 g/l"
            follow_up["closed_after_days"] = 8
        out_follow_ups.append(follow_up)

    # Pest traps, concentrated where tuber moth is a real problem.
    readings = []
    for i in range(traps):
        district, village, lat0, lon0 = rng.choice(LOCATIONS[:6])
        for day in range(0, days, 7):
            readings.append(
                {
                    "device_id": "demo-trap-%02d" % i,
                    "device_type": "pheromone_trap",
                    "metric": "trap_count",
                    "value": float(rng.randint(3, 42)),
                    "unit": "moths/week",
                    "crop": "potato",
                    "district": district,
                    "latitude": round(lat0 + rng.uniform(-0.03, 0.03), 5),
                    "longitude": round(lon0 + rng.uniform(-0.03, 0.03), 5),
                    "geo_cell": geo_cell(lat0, lon0),
                    "day_offset": day,
                }
            )

    return {
        "format": 1,
        "generator": "mobileapp/tools/export_demo_dataset.py",
        "seed": seed,
        "window_days": days,
        "note": (
            "Synthetic demonstration data. Every record is relative to the "
            "current date at read time; the app materialises the dates. Cases "
            "carry model_version 'demo-seed' and farmer names starting 'Demo', "
            "so they can always be told apart from real field reports."
        ),
        "cases": out_cases,
        "follow_ups": out_follow_ups,
        "sensor_readings": readings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    ap.add_argument("--cases", type=int, default=120)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--traps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    # 90 days by default, not the seeder's 30: the dashboard offers a 90-day
    # window, and a 30-day dataset makes the widest setting look identical to
    # the middle one.
    built = build(args.cases, args.days, args.traps, args.seed)
    payload = json.dumps(built, ensure_ascii=False, indent=1, sort_keys=False)

    if args.check:
        if not OUT.exists():
            print("Missing %s; run with --write." % OUT)
            return 1
        if OUT.read_text(encoding="utf-8") != payload:
            print("Demo dataset is stale. Run: "
                  "python mobileapp/tools/export_demo_dataset.py --write")
            return 1
        print("Demo dataset matches the generator.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    print(
        "Wrote %s: %d cases, %d follow-ups, %d trap readings (%.0f KB)"
        % (
            OUT.relative_to(REPO),
            len(built["cases"]),
            len(built["follow_ups"]),
            len(built["sensor_readings"]),
            OUT.stat().st_size / 1024,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
