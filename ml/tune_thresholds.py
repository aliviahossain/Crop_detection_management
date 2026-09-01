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
# Precision/recall move sharply at low confidence and flatten out well before
# 0.9. A uniform grid across 0.05-0.90 spent half its steps in a region where
# recall is already near zero, while under-resolving the part that decides the
# answer. Fine steps below the knee, coarse above it.
FINE_MAX = 0.60
FINE_SHARE = 0.8


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


def label_for(img_path: Path) -> Path | None:
    """`.../images/<split>/x.jpg` -> `.../labels/<split>/x.txt` (YOLO layout).

    Returns None when no `images` path component exists, rather than handing
    back the unchanged image path with a .txt suffix. The old version fell
    through silently: `load_ground_truth` then saw no file, treated the image as
    having zero ground-truth boxes, and every prediction on it counted as a
    false positive -- quietly biasing the whole sweep toward higher thresholds.
    A tuning run that reports nothing wrong while measuring nothing real is
    worse than one that fails.
    """
    parts = list(img_path.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            return Path(*parts).with_suffix(".txt")
    sibling = img_path.parent.parent / "labels" / img_path.parent.name / f"{img_path.stem}.txt"
    return sibling if sibling.exists() else None


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
    unreadable: list[str] = []
    no_label: list[str] = []
    for img_path in images:
        try:
            with Image.open(img_path) as im:
                width, height = im.size
        except (OSError, ValueError) as exc:
            # One truncated file used to abort the entire sweep with no partial
            # results after a full inference pass had already been paid for.
            unreadable.append(f"{img_path.name}: {exc}")
            continue

        label_path = label_for(img_path)
        if label_path is None or not label_path.exists():
            no_label.append(img_path.name)
            continue
        gt = load_ground_truth(label_path, width, height)

        try:
            res = model.predict(source=str(img_path), conf=0.001, iou=0.45, verbose=False)[0]
        except Exception as exc:
            unreadable.append(f"{img_path.name}: inference failed ({exc})")
            continue
        preds = [
            (int(b.cls.item()), float(b.conf.item()), [float(v) for v in b.xyxy[0].tolist()])
            for b in res.boxes
        ]
        records.append({"gt": gt, "preds": preds})

    if unreadable:
        print(f"  ! skipped {len(unreadable)} unreadable image(s):", file=sys.stderr)
        for line in unreadable[:5]:
            print(f"      {line}", file=sys.stderr)
    if no_label:
        print(
            f"  ! {len(no_label)} image(s) had no ground-truth label and were EXCLUDED. "
            "Counting them as empty would bias the sweep.",
            file=sys.stderr,
        )
    if not records:
        print(
            "No usable validation images with ground truth. Cannot tune thresholds.",
            file=sys.stderr,
        )
        return 1
    # Losing most of the val set invalidates the tuning, so refuse rather than
    # emit thresholds fitted to a handful of images.
    usable_share = len(records) / len(images)
    if usable_share < 0.5:
        print(
            f"Only {len(records)}/{len(images)} ({usable_share:.0%}) validation images were "
            "usable. Refusing to tune thresholds on that - fix the dataset layout first.",
            file=sys.stderr,
        )
        return 1
    print(f"Using {len(records)} of {len(images)} validation images.")

    n_fine = max(2, int(args.steps * FINE_SHARE))
    n_coarse = max(1, args.steps - n_fine)
    grid = [
        MIN_THRESHOLD + i * (FINE_MAX - MIN_THRESHOLD) / (n_fine - 1) for i in range(n_fine)
    ] + [
        FINE_MAX + (i + 1) * (MAX_THRESHOLD - FINE_MAX) / n_coarse for i in range(n_coarse)
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

    # The fallback for a class with no tuned entry must be the STRICTEST tuned
    # threshold, not the loosest. min() picked a disease-class threshold, which
    # is deliberately permissive because the triage layer catches its false
    # positives -- applying that to an untuned class would flood advisories with
    # detections nothing downstream is expecting. An unknown class has no
    # evidence behind it, so it should clear the highest bar we have measured.
    default = round(max(r["threshold"] for r in results.values()), 3)
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
        "default_rationale": (
            "Strictest tuned threshold. Applies only to a class with no tuned entry, where "
            "there is no evidence to justify anything more permissive."
        ),
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
