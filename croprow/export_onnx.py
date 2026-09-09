"""Export the trained croprow model to ONNX for torch-free serving.

The backend serves croprow/models/best.onnx to the browser (on-device inference)
and runs it server-side with numpy -- no torch at request time. This script is
the one-time bridge from the trained best.pt to that ONNX.

Run it in the croprow env (the one with torch + ultralytics; see croprow/README):

    croprow/.venv/Scripts/python croprow/export_onnx.py

It writes croprow/models/best.onnx next to best.pt. imgsz 640 matches the
backend and browser letterbox (INPUT_SIZE = 640).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PT = HERE / "models" / "best.pt"
IMGSZ = 640


def main() -> int:
    if not PT.exists():
        print(f"No weights at {PT}. Train first (croprow/notebooks/03_train.ipynb).")
        return 1
    try:
        from ultralytics import YOLO
    except ImportError:
        print(
            "ultralytics is not installed in this environment. Use the croprow env:\n"
            "    croprow/.venv/Scripts/python croprow/export_onnx.py"
        )
        return 1

    model = YOLO(str(PT))
    # opset 12 + fixed imgsz keeps the export compatible with onnxruntime-web.
    out = model.export(format="onnx", imgsz=IMGSZ, opset=12, simplify=True)
    dest = HERE / "models" / "best.onnx"
    exported = Path(out)
    if exported.resolve() != dest.resolve():
        dest.write_bytes(exported.read_bytes())
    print(f"Wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB). CropRow lab is now live on-device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
