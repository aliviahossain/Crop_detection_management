"""Build the secondary-risk-layer training CSV from accumulated real cases.

This is the missing link that turns "XGBoost layer inactive by design" from a
permanent state into a milestone. The brief is right that no ready-made dataset
links weather + crop stage + variety + soil + pest history to outbreak events
for Indian crops -- but this system *generates* exactly that dataset as it runs.

How a row is built
------------------
For every expert-confirmed case with coordinates:

* **Features** are recomputed from the weather cached at that location for the
  window *before* the case was reported -- the same features the live risk
  engine uses, including what the agronomic rules scored at the time.
* **Label** (`outbreak`) is 1 if a confirmed disease case occurred at that
  location within the following `--horizon-days`, else 0.

Because features come from before the observation and the label from after, the
row is causally ordered and there is no leakage of the outcome into the inputs.

Three guards, because a bad dataset here is worse than no dataset
-----------------------------------------------------------------
1. **Refuses to export seeded demo data** unless `--allow-demo` is passed. The
   demo rows are synthetic; a model fitted on them would look trained and behave
   like noise, and would then silently adjust real farmers' risk scores.
2. **Refuses rows whose weather window is synthetic backfill** unless
   `--allow-synthetic`. Features invented by our own generator cannot teach a
   model anything about real weather.
3. **Reports class balance**, because a dataset of 95% non-outbreaks trains a
   model that predicts "no outbreak" perfectly and uselessly.

    python scripts/export_risk_dataset.py --out data/risk_training.csv
    python ml/train_risk_xgb.py --csv data/risk_training.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Must match ml/train_risk_xgb.py and services/risk_secondary.FEATURE_ORDER.
FEATURE_ORDER = [
    "rule_score",
    "temp_mean_c",
    "humidity_mean",
    "rainfall_total_mm",
    "wetness_hours_7d",
    "crop_stage_index",
    "variety_susceptibility",
    "soil_drainage_index",
    "local_history_count",
    "trap_count_mean",
]
MIN_ROWS = 200  # train_risk_xgb.py refuses below this


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--horizon-days", type=int, default=14,
                    help="An outbreak counts if confirmed within this many days after the row.")
    ap.add_argument("--lookback-days", type=int, default=7,
                    help="Weather window used to compute features.")
    ap.add_argument("--radius-km", type=float, default=15.0)
    ap.add_argument("--allow-demo", action="store_true",
                    help="Include seeded demo cases. Never use for a deployed model.")
    ap.add_argument("--allow-synthetic", action="store_true",
                    help="Include rows whose weather window was synthetic backfill.")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.database import SessionLocal, init_db
    from app.models import Case, ReviewStatus
    from app.services import risk_models
    from app.services.geo import haversine_km
    from app.services.risk_engine import (
        CROP_STAGE_INDEX,
        DEFAULT_VARIETY_FACTOR,
        SOIL_DRAINAGE_INDEX,
        VARIETY_SUSCEPTIBILITY,
    )
    from app.services.weather import get_series

    init_db()
    db = SessionLocal()
    try:
        confirmed = list(
            db.scalars(
                select(Case)
                .where(Case.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.CORRECTED]))
                .where(Case.latitude.is_not(None))
                .order_by(Case.created_at)
            ).all()
        )
        if not confirmed:
            print(
                "No expert-confirmed cases with coordinates yet. This dataset is a by-product "
                "of the review queue -- confirm cases in /review first.",
                file=sys.stderr,
            )
            return 1

        demo = [c for c in confirmed if (c.farmer_name or "").startswith("Demo ")]
        if demo and not args.allow_demo:
            print(
                f"{len(demo)} of {len(confirmed)} confirmed cases are seeded demo data.\n"
                "Refusing to export: a model fitted on synthetic cases would look trained and\n"
                "behave like noise, then silently adjust real farmers' risk scores.\n"
                "Pass --allow-demo only to smoke-test the pipeline, never for a deployed model.",
                file=sys.stderr,
            )
            return 1
        pool = confirmed if args.allow_demo else [c for c in confirmed if c not in demo]

        # Outbreak lookups: confirmed *disease* cases, by location and time.
        outbreaks = [
            c for c in confirmed
            if c.effective_class in {"potato_early_blight", "potato_late_blight"}
        ]

        rows: list[dict] = []
        skipped: Counter = Counter()

        for case in pool:
            series = get_series(
                db, case.latitude, case.longitude,
                past_days=args.lookback_days, forecast_days=0,
                now=case.created_at.replace(tzinfo=None),
            )
            if series.synthetic and not args.allow_synthetic:
                skipped["synthetic_weather"] += 1
                continue

            days = risk_models.summarise_days(series.points)
            if not days:
                skipped["no_weather"] += 1
                continue

            smith = risk_models.smith_period(days)
            beaumont = risk_models.beaumont_period(series.points)
            rule_score = max(smith.score, beaumont.score * 0.7)
            summary = series.summary()

            history = sum(
                1 for o in outbreaks
                if o.id != case.id
                and o.created_at < case.created_at
                and o.created_at >= case.created_at - timedelta(days=21)
                and haversine_km(case.latitude, case.longitude, o.latitude, o.longitude)
                <= args.radius_km
            )

            # Label: did a confirmed disease case follow, here, within the horizon?
            label = int(any(
                o.created_at > case.created_at
                and o.created_at <= case.created_at + timedelta(days=args.horizon_days)
                and haversine_km(case.latitude, case.longitude, o.latitude, o.longitude)
                <= args.radius_km
                for o in outbreaks
            ))

            rows.append(
                {
                    "rule_score": round(rule_score, 4),
                    "temp_mean_c": summary.get("temp_mean_c", 0.0),
                    "humidity_mean": summary.get("humidity_mean", 0.0),
                    "rainfall_total_mm": summary.get("rainfall_total_mm", 0.0),
                    "wetness_hours_7d": sum(d.wetness_hours for d in days),
                    "crop_stage_index": CROP_STAGE_INDEX.get(
                        (case.crop_stage or "").lower().replace(" ", "_"), 2
                    ),
                    "variety_susceptibility": VARIETY_SUSCEPTIBILITY.get(
                        (case.variety or "").strip().lower(), DEFAULT_VARIETY_FACTOR
                    ),
                    "soil_drainage_index": SOIL_DRAINAGE_INDEX.get(
                        (case.soil_condition or "").lower().replace(" ", "_"), 0.5
                    ),
                    "local_history_count": history,
                    "trap_count_mean": 0.0,
                    "outbreak": label,
                    # Context columns, ignored by training but useful for auditing.
                    "case_id": case.id,
                    "district": case.district or "",
                    "observed_at": case.created_at.date().isoformat(),
                }
            )

        if not rows:
            print(f"No usable rows. Skipped: {dict(skipped)}", file=sys.stderr)
            return 1

        args.out.parent.mkdir(parents=True, exist_ok=True)
        fields = FEATURE_ORDER + ["outbreak", "case_id", "district", "observed_at"]
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        positives = sum(r["outbreak"] for r in rows)
        districts = Counter(r["district"] or "unknown" for r in rows)
        print(f"Wrote {len(rows)} rows to {args.out}")
        print(f"  outbreak = 1 : {positives}  ({positives / len(rows):.1%})")
        print(f"  outbreak = 0 : {len(rows) - positives}")
        print(f"  districts    : {dict(districts)}")
        if skipped:
            print(f"  skipped      : {dict(skipped)}")

        if len(rows) < MIN_ROWS:
            print(
                f"\n{len(rows)} rows is below the {MIN_ROWS}-row floor that ml/train_risk_xgb.py "
                "enforces. Keep collecting confirmed cases -- the agronomic models carry the "
                "forecast fine in the meantime.",
                file=sys.stderr,
            )
        if positives == 0 or positives == len(rows):
            print(
                "\nOnly one outcome class present -- nothing to learn. This usually means the "
                "horizon or radius is too wide or too narrow.",
                file=sys.stderr,
            )
        elif min(positives, len(rows) - positives) / len(rows) < 0.1:
            print(
                f"\nWarning: classes are imbalanced ({positives / len(rows):.1%} positive). "
                "XGBoost will need scale_pos_weight, which train_risk_xgb.py sets automatically.",
                file=sys.stderr,
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
