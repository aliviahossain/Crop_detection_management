"""Evaluate the trained model, reporting LAB and FIELD performance separately.

A single mAP number is the most misleading thing an ML pipeline can produce
here. PlantVillage images are one leaf on a uniform grey background under even
lighting; a model gets ~0.95+ mAP50 on that split almost regardless of whether
it has learnt anything about disease, because the task is nearly trivial. The
same model on a farmer's phone photo -- soil, other leaves, shadow, motion blur
-- can be dramatically worse.

Quoting the lab number as "our accuracy" is the single easiest way to be caught
out under questioning, and more importantly it means you do not know how the
system will behave in a field.

So this script evaluates against the per-source val lists that
`prepare_dataset.py` writes (`data_lab.yaml` / `data_field.yaml`) and prints
them side by side, with the gap called out. If there is no field split, it says
so instead of quietly reporting the lab number as the headline.

    python ml/evaluate.py --weights ml/weights/best.pt \
        --data datasets/potato_yolo/data.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]
# A lab-to-field mAP50 drop beyond this means the model has learnt the
# background, not the disease.
CONCERNING_GAP = 0.20


def run_split(model, data_yaml: Path, imgsz: int, split_name: str) -> dict | None:
    if not data_yaml.exists():
        return None
    print(f"\nEvaluating: {split_name}  ({data_yaml.name})")
    metrics = model.val(data=str(data_yaml), imgsz=imgsz, verbose=False)
    per_class = {}
    maps = list(getattr(metrics.box, "maps", []) or [])
    for i, name in enumerate(CLASS_NAMES):
        if i < len(maps):
            per_class[name] = round(float(maps[i]), 4)
    return {
        "split": split_name,
        "map50": round(float(getattr(metrics.box, "map50", 0.0)), 4),
        "map50_95": round(float(getattr(metrics.box, "map", 0.0)), 4),
        "precision": round(float(getattr(metrics.box, "mp", 0.0)), 4),
        "recall": round(float(getattr(metrics.box, "mr", 0.0)), 4),
        "per_class_map50_95": per_class,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--weights", type=Path, default=Path("ml/weights/best.pt"))
    ap.add_argument("--data", type=Path, required=True, help="data.yaml from prepare_dataset.py")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--out", type=Path, default=Path("ml/weights/evaluation.json"))
    args = ap.parse_args()

    if not args.weights.exists():
        print(f"No weights at {args.weights}", file=sys.stderr)
        return 1

    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    root = args.data.parent

    results = []
    for yaml_name, label in (
        (args.data.name, "combined"),
        ("data_lab.yaml", "lab (PlantVillage)"),
        ("data_field.yaml", "field (real conditions)"),
    ):
        res = run_split(model, root / yaml_name, args.imgsz, label)
        if res:
            results.append(res)

    print("\n" + "=" * 74)
    print(f"  {'split':<26}{'mAP50':>9}{'mAP50-95':>11}{'precision':>11}{'recall':>9}")
    print("-" * 74)
    for r in results:
        print(
            f"  {r['split']:<26}{r['map50']:>9.4f}{r['map50_95']:>11.4f}"
            f"{r['precision']:>11.4f}{r['recall']:>9.4f}"
        )
    print("=" * 74)

    lab = next((r for r in results if r["split"].startswith("lab")), None)
    field = next((r for r in results if r["split"].startswith("field")), None)

    verdict: str
    if field is None:
        verdict = (
            "NO FIELD SPLIT. Every number above is a LAB metric measured on uniform-background "
            "PlantVillage images. Do not present it as field accuracy. Add field-condition "
            "images with prepare_dataset.py --annotated and re-run."
        )
        print(f"\n{verdict}", file=sys.stderr)
    else:
        gap = (lab["map50"] - field["map50"]) if lab else 0.0
        print(f"\n  lab -> field mAP50 gap: {gap:+.4f}")
        if gap > CONCERNING_GAP:
            verdict = (
                f"The model drops {gap:.2f} mAP50 from lab to field. That is the signature of a "
                "model that has learnt the uniform background rather than the disease. Add more "
                "field images and retrain before deploying."
            )
            print(f"\n  WARNING: {verdict}", file=sys.stderr)
        else:
            verdict = (
                f"Field performance is within {gap:.2f} mAP50 of lab. Quote the FIELD number "
                f"({field['map50']:.3f} mAP50) as the honest headline figure."
            )
            print(f"\n  {verdict}")

    payload = {
        "weights": str(args.weights),
        "imgsz": args.imgsz,
        "results": results,
        "headline_metric": (field or lab or {}).get("map50"),
        "headline_source": (field or lab or {}).get("split"),
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
