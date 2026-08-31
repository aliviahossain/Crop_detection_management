"""Tune per-class confidence thresholds on the validation set.

The default 0.25 that everyone ships with is an arbitrary number from the
ultralytics examples. It encodes an assumption -- that a false positive and a
false negative cost the same -- which is simply wrong here:

* **Missing late blight is catastrophic.** An unprotected crop can be destroyed
  in 7-10 days. A false negative costs the farmer the field.
* **A false positive costs a spray**, which is real money and real residue --
  but the triage layer already withholds the dose table below
  `LOW_CONFIDENCE_THRESHOLD` and routes the case to an extension officer. The
  system has a second line of defence against false positives; it has none
  against false negatives.
* **A false "healthy" is the dangerous direction of that class.** Telling a
  farmer with early-stage blight that the crop is fine is how the delayed
  treatment in the problem statement happens.

So the objective differs per class:

| Class | Optimised for | Why |
|---|---|---|
| `potato_early_blight` | F2 (recall-weighted) | Catch it; triage filters the uncertain ones |
| `potato_late_blight`  | F2 (recall-weighted) | Fast-moving, highest cost of a miss |
| `potato_healthy`      | F0.5 (precision-weighted) | Only say "healthy" when sure |

Output is `ml/weights/thresholds.json`, which the serving detector loads
automatically. If it is absent the backend falls back to the single
`DETECTION_CONF_THRESHOLD` from the environment.

    python ml/tune_thresholds.py --weights ml/weights/best.pt \
        --data datasets/potato_yolo/data.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]
# Beta > 1 weights recall; beta < 1 weights precision.
CLASS_BETA = {
    "potato_early_blight": 2.0,
    "potato_late_blight": 2.0,
    "potato_healthy": 0.5,
}
IOU_MATCH = 0.5
# Never recommend a threshold below this -- under it, box noise floods the
# advisory with spurious detections the farmer has to sort out.
MIN_THRESHOLD = 0.05
MAX_THRESHOLD = 0.90


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / (area_a + area_b - inter + 1e-9)


def label_for(img_path: Path) -> Path:
    """`.../images/<split>/x.jpg` -> `.../labels/<split>/x.txt` (YOLO layout)."""
    parts = list(img_path.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            break
    return Path(*parts).with_suffix(".txt")


def load_ground_truth(label_path: Path, width: int, height: int) -> list[tuple[int, list[float]]]:
    """YOLO normalised cxcywh -> (class_id, xyxy pixels)."""
    if not label_path.exists():
        return []
    out = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        cid = int(float(parts[0]))
        cx, cy, w, h = (float(v) for v in parts[1:5])
        out.append(
            (
                cid,
                [
                    (cx - w / 2) * width,
                    (cy - h / 2) * height,
                    (cx + w / 2) * width,
                    (cy + h / 2) * height,
                ],
            )
        )
    return out


def fbeta(precision: float, recall: float, beta: float) -> float:
    if precision <= 0 and recall <= 0:
        return 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    return 0.0 if denom <= 0 else (1 + b2) * precision * recall / denom


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--weights", type=Path, default=Path("ml/weights/best.pt"))
    ap.add_argument("--data", type=Path, required=True, help="data.yaml (uses its val split)")
    ap.add_argument("--out", type=Path, default=Path("ml/weights/thresholds.json"))
    ap.add_argument("--steps", type=int, default=36, help="Threshold grid resolution")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    if not args.weights.exists():
        print(f"No weights at {args.weights}", file=sys.stderr)
        return 1

    import yaml
    from PIL import Image
    from ultralytics import YOLO

    cfg = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    root = Path(cfg.get("path", args.data.parent))
    val_entry = cfg["val"]
    val_path = root / val_entry
    if val_path.suffix == ".txt":
        images = [Path(p) for p in val_path.read_text(encoding="utf-8").split() if p.strip()]
    else:
        images = sorted(
            p for p in val_path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
    if not images:
        print(f"No validation images found under {val_path}", file=sys.stderr)
        return 1
    print(f"Sweeping thresholds over {len(images)} validation images.")

    model = YOLO(str(args.weights))
    # Predict once at a very low threshold, then sweep offline. One inference
    # pass instead of one per candidate threshold.
    records: list[dict] = []
    for img_path in images:
        with Image.open(img_path) as im:
            width, height = im.size
        gt = load_ground_truth(label_for(img_path), width, height)

        res = model.predict(source=str(img_path), conf=0.001, iou=0.45, verbose=False)[0]
        preds = [
            (int(b.cls.item()), float(b.conf.item()), [float(v) for v in b.xyxy[0].tolist()])
            for b in res.boxes
        ]
        records.append({"gt": gt, "preds": preds})

    grid = [
        MIN_THRESHOLD + i * (MAX_THRESHOLD - MIN_THRESHOLD) / (args.steps - 1)
        for i in range(args.steps)
    ]

    results: dict[str, dict] = {}
    print("\nPer-class threshold sweep")
    print("-" * 78)
    for cid, class_name in enumerate(CLASS_NAMES):
        beta = CLASS_BETA[class_name]
        best = {"threshold": 0.25, "score": -1.0, "precision": 0.0, "recall": 0.0}
        curve = []
        for thr in grid:
            tp = fp = fn = 0
            for rec in records:
                gt_boxes = [box for c, box in rec["gt"] if c == cid]
                pred_boxes = sorted(
                    [(conf, box) for c, conf, box in rec["preds"] if c == cid and conf >= thr],
                    key=lambda x: -x[0],
                )
                matched = set()
                for _conf, pbox in pred_boxes:
                    hit = -1
                    best_iou = IOU_MATCH
                    for gi, gbox in enumerate(gt_boxes):
                        if gi in matched:
                            continue
                        score = iou(pbox, gbox)
                        if score >= best_iou:
                            best_iou, hit = score, gi
                    if hit >= 0:
                        matched.add(hit)
                        tp += 1
                    else:
                        fp += 1
                fn += len(gt_boxes) - len(matched)

            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            score = fbeta(precision, recall, beta)
            curve.append(
                {"threshold": round(thr, 3), "precision": round(precision, 4),
                 "recall": round(recall, 4), "score": round(score, 4)}
            )
            if score > best["score"]:
                best = {
                    "threshold": round(thr, 3),
                    "score": round(score, 4),
                    "precision": round(precision, 4),
                    "recall": round(recall, 4),
                }

        objective = f"F{beta:g}"
        print(
            f"  {class_name:<24} {objective:>5}  thr={best['threshold']:.3f}  "
            f"P={best['precision']:.3f}  R={best['recall']:.3f}  {objective}={best['score']:.3f}"
        )
        results[class_name] = {**best, "beta": beta, "objective": objective, "curve": curve}

    default = round(min(r["threshold"] for r in results.values()), 3)
    payload = {
        "tuned_on": str(args.data),
        "tuned_at": date.today().isoformat(),
        "weights": str(args.weights),
        "val_images": len(images),
        "iou_match": IOU_MATCH,
        "rationale": (
            "Disease classes are tuned for F2 (recall-weighted): a missed blight costs the "
            "crop, while a false positive is caught by the triage layer, which withholds the "
            "dose table below the low-confidence threshold. potato_healthy is tuned for F0.5 "
            "(precision-weighted): only say healthy when sure, because a false 'healthy' is "
            "exactly the delayed-treatment failure the problem statement describes."
        ),
        "default": default,
        "per_class": {name: r["threshold"] for name, r in results.items()},
        "metrics": {
            name: {k: r[k] for k in ("precision", "recall", "score", "objective", "beta")}
            for name, r in results.items()
        },
        "curves": {name: r["curve"] for name, r in results.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nWrote {args.out}")
    print("The backend loads this automatically -- GET /detect/status will show the")
    print("per-class thresholds in use instead of the single env default.")

    weak = [n for n, r in results.items() if r["recall"] < 0.7]
    if weak:
        print(
            f"\nWarning: recall is below 0.70 at the best threshold for: {', '.join(weak)}. "
            "No threshold fixes an under-trained class - get more images for it.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
