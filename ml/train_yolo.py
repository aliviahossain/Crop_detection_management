"""Train the potato detector: 3 classes, 100 epochs.

Run on Kaggle (free GPU, 30 hr/week) or Colab. **Do not run this on the dev
laptop** -- the brief pins a 16 GB RAM machine with very little C: space; only
the exported weights (a few MB) come back down.

    python ml/train_yolo.py --data /kaggle/working/potato_yolo/data.yaml \
        --model yolov8s.pt --epochs 100 --imgsz 640 --batch 16

Defaults chosen deliberately:

* **yolov8s** (small) is the default, not nano. Nano is the least accurate
  variant in the family, and accuracy is what matters when a wrong answer means
  a wrong pesticide. `s` roughly triples the parameters (11.2M vs 3.2M) for a
  meaningful mAP gain, and on CPU it still lands inside the latency budget --
  verify on your own hardware with `ml/benchmark_inference.py` rather than
  taking that on trust.

  Train `yolov8n` as well (`--model yolov8n.pt`) if you want the offline /
  on-device story: ship `s` on the server, `n` in a phone build. Compare them
  with `benchmark_inference.py --model a.onnx --model b.onnx`, and pick the
  largest variant that stays inside your latency budget.

* **100 epochs** with `patience=25`. Early stopping keeps a converged run from
  burning GPU quota; 100 is the ceiling, not a promise.

* **Conservative augmentation.** No vertical flip and low hue jitter: leaf
  lesion colour *is* the diagnostic signal, and aggressive colour augmentation
  teaches the model to ignore the one feature that separates early from late
  blight. Geometry is augmented freely; colour is not.

  This matters more than usual here because the dataset is small. Augmentation
  is doing real work -- but the *wrong* augmentation on a small dataset destroys
  the signal faster than it regularises the model.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="Path to data.yaml")
    ap.add_argument(
        "--model", default="yolov8s.pt",
        help="yolov8s.pt (default, accuracy) | yolov8n.pt (offline/mobile) | yolov8m.pt",
    )
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--patience", type=int, default=25)
    ap.add_argument("--device", default=0, help="0 for the Kaggle GPU, 'cpu' to force CPU")
    ap.add_argument("--project", type=Path, default=Path("runs/potato"))
    ap.add_argument("--name", default=None, help="Run name; defaults to <model>_3class_<epochs>e")
    ap.add_argument("--export-dir", type=Path, default=Path("ml/weights"))
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()
    if args.name is None:
        args.name = f"{Path(args.model).stem}_3class_{args.epochs}e"

    from ultralytics import YOLO

    model = YOLO(args.model)
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        device=args.device,
        project=str(args.project),
        name=args.name,
        seed=42,
        deterministic=True,
        pretrained=True,
        optimizer="auto",
        cos_lr=True,
        # --- augmentation: geometry yes, colour sparingly ---
        hsv_h=0.010,   # hue is the diagnostic signal -- barely touch it
        hsv_s=0.5,
        hsv_v=0.3,
        degrees=15.0,
        translate=0.10,
        scale=0.40,
        fliplr=0.5,
        flipud=0.0,    # leaves are photographed the right way up
        mosaic=1.0,
        close_mosaic=10,  # last 10 epochs without mosaic, so val matches reality
        plots=True,
        val=True,
    )

    save_dir = Path(results.save_dir if hasattr(results, "save_dir") else args.project / args.name)
    best = save_dir / "weights" / "best.pt"
    print(f"\nBest weights: {best}")

    metrics = model.val(data=str(args.data), split="val", device=args.device)
    summary = {
        "model": args.model,
        "epochs_requested": args.epochs,
        "imgsz": args.imgsz,
        "classes": CLASS_NAMES,
        "map50": float(getattr(metrics.box, "map50", 0.0)),
        "map50_95": float(getattr(metrics.box, "map", 0.0)),
        "precision": float(getattr(metrics.box, "mp", 0.0)),
        "recall": float(getattr(metrics.box, "mr", 0.0)),
        "per_class_map50": {
            CLASS_NAMES[i]: float(v)
            for i, v in enumerate(getattr(metrics.box, "maps", []) or [])
            if i < len(CLASS_NAMES)
        },
    }
    print("\nValidation summary:")
    print(json.dumps(summary, indent=2))

    if not args.no_export and best.exists():
        args.export_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, args.export_dir / "best.pt")
        (args.export_dir / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        # ONNX is the serving artifact -- CPU-fast and torch-free at runtime.
        onnx_path = YOLO(str(best)).export(format="onnx", imgsz=args.imgsz, opset=12, simplify=True)
        shutil.copy2(onnx_path, args.export_dir / "best.onnx")
        print(f"\nExported to {args.export_dir}/best.pt and best.onnx")
        print("Download ml/weights/ from Kaggle and drop it into the repo -- that is the only")
        print("artifact the laptop needs; the backend picks it up on the next request.")
        print("\nNext, in this order:")
        print(f"  python ml/evaluate.py        --weights {best} --data {args.data}")
        print(f"  python ml/tune_thresholds.py --weights {best} --data {args.data}")
        print("  python ml/benchmark_inference.py --model ml/weights/best.onnx")
        print("\nThe mAP above is measured on whatever mix prepare_dataset.py built. If that")
        print("was PlantVillage only it is a LAB number -- evaluate.py separates lab from field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
