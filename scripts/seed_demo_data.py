"""Seed realistic demo data so the map and dashboard have something to show.

The hotspot map and officer dashboard are only meaningful with a body of cases
behind them, and real field reports accumulate over months. This generates a
plausible month of activity across Maharashtra potato districts -- including
expert reviews, follow-up outcomes and trap readings -- so the whole system can
be demonstrated end to end on day one.

Everything it writes is marked `farmer_name` starting with "Demo" and can be
removed with `--reset`. It is demo data, and the code says so.

    python scripts/seed_demo_data.py --cases 120
    python scripts/seed_demo_data.py --reset
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Real potato-growing pockets in Maharashtra, with approximate coordinates.
LOCATIONS = [
    ("Pune", "Manchar", 19.0009, 73.9403),
    ("Pune", "Ambegaon", 19.1180, 73.7350),
    ("Pune", "Junnar", 19.2050, 73.8750),
    ("Nashik", "Dindori", 20.2030, 73.8300),
    ("Nashik", "Niphad", 20.0800, 74.1100),
    ("Satara", "Wai", 17.9500, 73.8900),
    ("Satara", "Khandala", 18.0400, 73.9600),
    ("Ahmednagar", "Sangamner", 19.5700, 74.2100),
    ("Beed", "Ashti", 18.8100, 74.9700),
    ("Nagpur", "Katol", 21.2700, 78.5900),
]
VARIETIES = ["Kufri Jyoti", "Kufri Pukhraj", "Kufri Badshah", "Kufri Chandramukhi", "Kufri Himalini"]
STAGES = ["vegetative", "tuber_initiation", "tuber_bulking", "maturity"]
SOILS = ["well_drained", "normal", "poorly_drained", "clay"]
# Weighted so late blight dominates -- that is the realistic rabi-season picture
# and it is what makes a hotspot appear on the map.
CLASS_WEIGHTS = [("potato_late_blight", 0.5), ("potato_early_blight", 0.3), ("potato_healthy", 0.2)]
REVIEWERS = ["TAO Pune", "TAO Nashik", "SDAO Satara", "KVK Baramati"]


def weighted_choice(rng: random.Random, pairs):
    r = rng.random()
    cum = 0.0
    for value, weight in pairs:
        cum += weight
        if r < cum:
            return value
    return pairs[-1][0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=int, default=120)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--traps", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--reset", action="store_true", help="Delete previously seeded demo rows and exit")
    args = ap.parse_args()

    from sqlalchemy import delete, select

    from app.database import SessionLocal, init_db
    from app.models import (
        Case,
        CaseSource,
        FollowUp,
        FollowUpOutcome,
        ReviewStatus,
        RiskLevel,
        SensorReading,
        TrainingSample,
    )
    from app.services.geo import geo_cell

    init_db()
    db = SessionLocal()
    rng = random.Random(args.seed)

    try:
        if args.reset:
            demo_ids = [
                c.id
                for c in db.scalars(select(Case).where(Case.farmer_name.like("Demo %"))).all()
            ]
            if demo_ids:
                db.execute(delete(FollowUp).where(FollowUp.case_id.in_(demo_ids)))
                db.execute(delete(TrainingSample).where(TrainingSample.case_id.in_(demo_ids)))
                db.execute(delete(Case).where(Case.id.in_(demo_ids)))
            db.execute(delete(SensorReading).where(SensorReading.device_id.like("demo-trap-%")))
            db.commit()
            print(f"Removed {len(demo_ids)} demo cases and their demo trap readings.")
            return 0

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        created = 0
        for i in range(args.cases):
            district, village, lat0, lon0 = rng.choice(LOCATIONS)
            # Jitter within roughly 5 km so cases cluster into cells rather than
            # landing on one point.
            lat = lat0 + rng.uniform(-0.045, 0.045)
            lon = lon0 + rng.uniform(-0.045, 0.045)
            cls = weighted_choice(rng, CLASS_WEIGHTS)
            confidence = round(rng.uniform(0.42, 0.97), 3)
            created_at = now - timedelta(
                days=rng.randint(0, args.days), hours=rng.randint(0, 23)
            )

            if cls == "potato_healthy":
                risk_level, risk_score = RiskLevel.LOW, round(rng.uniform(0.05, 0.35), 3)
            elif cls == "potato_late_blight":
                risk_level, risk_score = (
                    RiskLevel.HIGH if rng.random() < 0.6 else RiskLevel.MEDIUM,
                    round(rng.uniform(0.45, 0.95), 3),
                )
            else:
                risk_level, risk_score = RiskLevel.MEDIUM, round(rng.uniform(0.3, 0.7), 3)

            low_conf = confidence < 0.55
            case = Case(
                created_at=created_at,
                source=CaseSource.IMAGE if rng.random() < 0.8 else CaseSource.RISK_FORECAST,
                farmer_name=f"Demo Farmer {i + 1:03d}",
                phone=f"9{rng.randint(100000000, 999999999)}",
                crop="potato",
                variety=rng.choice(VARIETIES),
                crop_stage=rng.choice(STAGES),
                soil_condition=rng.choice(SOILS),
                district=district,
                village=village,
                latitude=round(lat, 5),
                longitude=round(lon, 5),
                geo_cell=geo_cell(lat, lon),
                predicted_class=cls,
                confidence=confidence,
                detections=[
                    {
                        "class_key": cls,
                        "confidence": confidence,
                        "bbox": [40, 40, 280, 220],
                        "bbox_norm": [0.12, 0.16, 0.87, 0.91],
                    }
                ],
                model_version="demo-seed",
                risk_level=risk_level,
                risk_score=risk_score,
                escalate=low_conf or risk_level == RiskLevel.HIGH,
                escalation_reasons=[
                    {
                        "code": "low_confidence" if low_conf else "fast_moving_disease",
                        "message": "Seeded demo case.",
                        "action": "Confirm with an extension officer.",
                    }
                ],
                language=rng.choice(["mr", "mr", "en", "hi"]),
            )

            # About 55% get reviewed -- a realistic backlog for the review queue.
            if rng.random() < 0.55:
                if rng.random() < 0.78:
                    case.review_status = ReviewStatus.CONFIRMED
                    case.confirmed_class = cls
                else:
                    case.review_status = ReviewStatus.CORRECTED
                    others = [c for c, _ in CLASS_WEIGHTS if c != cls]
                    case.confirmed_class = rng.choice(others)
                case.reviewer = rng.choice(REVIEWERS)
                case.reviewed_at = created_at + timedelta(days=rng.randint(1, 3))
                case.reviewer_notes = "Field inspection completed."

            db.add(case)
            db.flush()

            follow_up = FollowUp(
                case_id=case.id,
                created_at=created_at,
                due_date=created_at + timedelta(days=7),
                notes="Seeded demo follow-up.",
            )
            if follow_up.due_date < now and rng.random() < 0.7:
                follow_up.outcome = weighted_choice(
                    rng,
                    [
                        (FollowUpOutcome.RESOLVED, 0.45),
                        (FollowUpOutcome.IMPROVING, 0.30),
                        (FollowUpOutcome.UNCHANGED, 0.17),
                        (FollowUpOutcome.WORSENED, 0.08),
                    ],
                )
                follow_up.treatment_applied = "Mancozeb 75% WP @ 2.5 g/l"
                follow_up.closed_at = follow_up.due_date + timedelta(days=1)
            db.add(follow_up)
            created += 1

        # Pest traps, concentrated where tuber moth is a real problem.
        for i in range(args.traps):
            district, village, lat0, lon0 = rng.choice(LOCATIONS[:6])
            for day in range(0, args.days, 7):
                db.add(
                    SensorReading(
                        device_id=f"demo-trap-{i:02d}",
                        device_type="pheromone_trap",
                        metric="trap_count",
                        value=float(rng.randint(3, 42)),
                        unit="moths/week",
                        crop="potato",
                        district=district,
                        latitude=round(lat0 + rng.uniform(-0.03, 0.03), 5),
                        longitude=round(lon0 + rng.uniform(-0.03, 0.03), 5),
                        geo_cell=geo_cell(lat0, lon0),
                        recorded_at=now - timedelta(days=day),
                    )
                )

        db.commit()
        print(f"Seeded {created} demo cases across {len(LOCATIONS)} locations, "
              f"{args.traps} trap devices.")
        print("Start the API and open the dashboard -- /hotspots and /dashboard/summary now "
              "have data. Remove it later with --reset.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
