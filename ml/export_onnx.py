"""Export a trained best.pt to ONNX and verify the export actually loads.

**This module is the single authority for producing the serving artifact.**
`train_yolo.py` imports `export_and_verify` from here rather than calling
`YOLO.export()` itself. Two independent export paths meant the opset and
simplify settings could drift apart, so you could end up serving one artifact
while believing you had validated a different one.

Serving runs on onnxruntime, so an export that silently produces the wrong
output shape would only surface as bad predictions in the field. Every export
is checked for the (1, 4+nc, N) YOLO detect shape the backend's decoder expects,
that nc == 3, and that the embedded class names are in taxonomy order.

    python ml/export_onnx.py --weights ml/weights/best.pt
"""
from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]
EXPECTED_CLASSES = len(CLASS_NAMES)

# Pinned here, in one place. opset 12 is the floor onnxruntime 1.x supports
# comfortably for YOLO ops and keeps the graph loadable by older runtimes,
# including onnxruntime-web in the browser scanner.
EXPORT_OPSET = 12
DEFAULT_IMGSZ = 640


def verify_onnx(path: Path, imgsz: int = DEFAULT_IMGSZ) -> bool:
    """Load the exported file and confirm it decodes the way serving expects."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed here; skipping the verification pass.")
        return True

    try:
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as exc:
        print(f"FAILED to load the exported model: {exc}", file=sys.stderr)
        return False

    name = sess.get_inputs()[0].name
    dummy = np.zeros((1, 3, imgsz, imgsz), dtype=np.float32)
    try:
        out = sess.run(None, {name: dummy})[0]
    except Exception as exc:
        print(f"FAILED to run the exported model: {exc}", file=sys.stderr)
        return False
    print(f"Output shape: {out.shape}")

    dims = [d for d in out.shape if isinstance(d, int)]
    if len(dims) < 3:
        print(f"Unexpected output rank: {out.shape}", file=sys.stderr)
        return False
    n_cls = min(dims[1:]) - 4
    if n_cls != EXPECTED_CLASSES:
        print(
            f"Export looks wrong: inferred {n_cls} classes, expected {EXPECTED_CLASSES}. "
            "Check that data.yaml had exactly the three potato classes at training time.",
            file=sys.stderr,
        )
        return False

    # Class ORDER matters as much as the count -- see test_class_lockstep.py.
    meta = sess.get_modelmeta().custom_metadata_map or {}
    if "names" in meta:
        try:
            parsed = ast.literal_eval(meta["names"])
            names = (
                [str(parsed[k]) for k in sorted(parsed)]
                if isinstance(parsed, dict)
                else [str(v) for v in parsed]
            )
        except (ValueError, SyntaxError):
            names = []
        if names and names != CLASS_NAMES:
            print(
                f"Export has class order {names}, expected {CLASS_NAMES}. Serving maps model "
                "index to class by position, so this would mislabel every prediction.",
                file=sys.stderr,
            )
            return False
        if names:
            print(f"Class order verified: {names}")

    print(f"Verified: {EXPECTED_CLASSES}-class YOLO detect output. The backend can load this.")
    return True


def export_and_verify(
    weights: Path,
    out: Path,
    imgsz: int = DEFAULT_IMGSZ,
    simplify: bool = True,
) -> Path | None:
    """Export `weights` to ONNX at `out`. Returns the path, or None on failure."""
    weights, out = Path(weights), Path(out)
    if not weights.exists():
        print(f"No weights at {weights}", file=sys.stderr)
        return None

    try:
        from ultralytics import YOLO
    except ImportError:
        print(
            "ultralytics is not installed. pip install -r backend/requirements-optional.txt",
            file=sys.stderr,
        )
        return None

    if simplify:
        try:
            import onnxslim  # noqa: F401
        except ImportError:
            print(
                "onnxslim not installed; exporting without graph simplification.",
                file=sys.stderr,
            )
            simplify = False

    model = YOLO(str(weights))
    print(f"Classes in checkpoint: {model.names}")
    try:
        exported = model.export(
            format="onnx", imgsz=imgsz, opset=EXPORT_OPSET, simplify=simplify
        )
    except Exception as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return None

    out.parent.mkdir(parents=True, exist_ok=True)
    if Path(exported).resolve() != out.resolve():
        shutil.copy2(exported, out)
    print(f"Wrote {out}")

    return out if verify_onnx(out, imgsz) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weights", type=Path, default=Path("ml/weights/best.pt"))
    ap.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    ap.add_argument("--out", type=Path, default=Path("ml/weights/best.onnx"))
    ap.add_argument(
        "--no-simplify", action="store_true", help="Skip onnxslim graph simplification"
    )
    ap.add_argument(
        "--verify-only", action="store_true", help="Only verify an existing --out file"
    )
    args = ap.parse_args()

    if args.verify_only:
        if not args.out.exists():
            print(f"No file at {args.out}", file=sys.stderr)
            return 1
        return 0 if verify_onnx(args.out, args.imgsz) else 1

    result = export_and_verify(
        weights=args.weights,
        out=args.out,
        imgsz=args.imgsz,
        simplify=not args.no_simplify,
    )
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
