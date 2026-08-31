"""Export expert-validated cases as the next training increment.

This is the concrete half of "learns from field confirmations". Every case an
extension officer confirms or corrects becomes a labelled sample; this script
packages the unexported ones into a YOLO-format folder you upload to Kaggle and
train on alongside the original data.

    python ml/export_feedback.py --out datasets/feedback_batch_01
    python ml/export_feedback.py --out ... --mark-exported

Deliberately a manual step, not a cron job. Retraining on field data without a
human looking at the batch first is how a model quietly degrades: a handful of
mislabelled confirmations, or a month where every photo came from one village,
will bias it. Print the summary, eyeball the balance, then train.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]
CLASS_INDEX = {n: i for i, n in enumerate(CLASS_NAMES)}
WEAK_BOX = "0.5 0.5 0.9 0.9"
MIN_BATCH = 50


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mark-exported", action="store_true", help="Flag the rows as exported")
    ap.add_argument("--include-exported", action="store_true", help="Re-export everything")
    ap.add_argument("--corrections-only", action="store_true",
                    help="Only cases where the model was wrong - the highest-value samples")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.database import SessionLocal, init_db
    from app.models import Case, TrainingSample

    init_db()
    db = SessionLocal()
    try:
        stmt = select(TrainingSample)
        if not args.include_exported:
            stmt = stmt.where(TrainingSample.exported.is_(False))
        if args.corrections_only:
            stmt = stmt.where(TrainingSample.was_model_correct.is_(False))
        samples = list(db.scalars(stmt).all())

        if not samples:
            print("Nothing to export. Expert reviews create these rows -- see /review/queue.")
            return 0

        img_dir = args.out / "images"
        lbl_dir = args.out / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        counts: Counter = Counter()
        skipped: list[str] = []
        manifest: list[dict] = []

        for s in samples:
            if s.label not in CLASS_INDEX:
                skipped.append(f"case {s.case_id}: label '{s.label}' outside the 3-class scope")
                continue
            if not s.image_path:
                skipped.append(f"case {s.case_id}: no image on file")
                continue
            src = REPO_ROOT / s.image_path
            if not src.exists():
                skipped.append(f"case {s.case_id}: image missing at {src}")
                continue

            stem = f"case{s.case_id}"
            shutil.copy2(src, img_dir / f"{stem}{src.suffix.lower()}")
            # Field photos have no boxes drawn on them; a weak full-frame box is
            # the honest default. Annotate the high-value corrections properly in
            # Roboflow before the next training run.
            (lbl_dir / f"{stem}.txt").write_text(
                f"{CLASS_INDEX[s.label]} {WEAK_BOX}\n", encoding="utf-8"
            )
            counts[s.label] += 1
            manifest.append(
                {
                    "case_id": s.case_id,
                    "label": s.label,
                    "model_was_correct": s.was_model_correct,
                    "model_version": s.model_version,
                    "image": f"images/{stem}{src.suffix.lower()}",
                }
            )
            if args.mark_exported:
                s.exported = True

        # District spread is the bias check that matters most in practice.
        case_ids = [m["case_id"] for m in manifest]
        districts = Counter(
            c.district or "unknown"
            for c in db.scalars(select(Case).where(Case.id.in_(case_ids))).all()
        ) if case_ids else Counter()

        (args.out / "manifest.json").write_text(
            json.dumps(
                {
                    "exported": len(manifest),
                    "by_class": dict(counts),
                    "by_district": dict(districts),
                    "corrections": sum(1 for m in manifest if not m["model_was_correct"]),
                    "samples": manifest,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        if args.mark_exported:
            db.commit()

        print(f"Exported {len(manifest)} samples to {args.out}")
        for cls in CLASS_NAMES:
            print(f"  {cls:24s} {counts.get(cls, 0)}")
        print(f"  corrections (model was wrong): {sum(1 for m in manifest if not m['model_was_correct'])}")
        print(f"  districts represented: {dict(districts)}")
        if skipped:
            print(f"\nSkipped {len(skipped)}:")
            for line in skipped[:10]:
                print(f"  - {line}")

        if len(manifest) < MIN_BATCH:
            print(
                f"\nOnly {len(manifest)} samples. Retraining on fewer than ~{MIN_BATCH} field "
                "images will not move the model and risks overfitting to one locality. "
                "Keep collecting."
            )
        if districts and max(districts.values()) / len(manifest) > 0.8:
            print(
                "\nWarning: over 80% of this batch comes from one district. Training on it will "
                "bias the model towards that locality's conditions."
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
