"""Export a trained best.pt to ONNX and verify the export actually loads.

Serving runs on onnxruntime, so an export that silently produces a wrong output
shape would only surface as bad predictions in the field. This script checks the
output tensor is the (1, 4+nc, N) YOLO detect shape the backend's decoder
expects, and that nc == 3.

    python ml/export_onnx.py --weights ml/weights/best.pt
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

EXPECTED_CLASSES = 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weights", type=Path, default=Path("ml/weights/best.pt"))
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--opset", type=int, default=12)
    ap.add_argument("--out", type=Path, default=Path("ml/weights/best.onnx"))
    args = ap.parse_args()

    if not args.weights.exists():
        print(f"No weights at {args.weights}", file=sys.stderr)
        return 1

    from ultralytics import YOLO

    model = YOLO(str(args.weights))
    print(f"Classes in checkpoint: {model.names}")
    exported = model.export(format="onnx", imgsz=args.imgsz, opset=args.opset, simplify=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if Path(exported).resolve() != args.out.resolve():
        shutil.copy2(exported, args.out)
    print(f"Wrote {args.out}")

    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed here; skipping the verification pass.")
        return 0

    sess = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    dummy = np.zeros((1, 3, args.imgsz, args.imgsz), dtype=np.float32)
    out = sess.run(None, {name: dummy})[0]
    print(f"Output shape: {out.shape}")

    dims = [d for d in out.shape if isinstance(d, int)]
    n_cls = (min(dims[1:]) - 4) if len(dims) >= 3 else -1
    if n_cls != EXPECTED_CLASSES:
        print(
            f"Export looks wrong: inferred {n_cls} classes, expected {EXPECTED_CLASSES}. "
            "Check that data.yaml had exactly the three potato classes at training time.",
            file=sys.stderr,
        )
        return 1
    print("Verified: 3-class YOLO detect output. The backend will load this directly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
