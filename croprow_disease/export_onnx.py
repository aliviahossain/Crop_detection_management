"""Export the trained croprow_disease model to ONNX for torch-free serving.

Mirrors croprow/export_onnx.py, with one difference that matters downstream:
this model has **two** classes, so a consumer decoding the raw ONNX output must
read 6 values per prediction (4 box + 2 class scores) rather than 5, and must
pick the argmax of the two class scores instead of taking the single objectness
column. A serving path written against the single-class croprow model will
silently mis-decode these outputs -- it will not error, it will just be wrong.

Run it in the croprow env (the one with torch + ultralytics):

    croprow/.venv/Scripts/python croprow_disease/export_onnx.py

Writes croprow_disease/models/best.onnx next to best.pt. imgsz 640 matches the
backend and browser letterbox used elsewhere in this repo (INPUT_SIZE = 640).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PT = HERE / "models" / "best.pt"
IMGSZ = 640
CLASS_NAMES = ["healthy", "unhealthy"]


def main() -> int:
    if not PT.exists():
        print(f"No weights at {PT}. Train first "
              "(croprow_disease/notebooks/03_train.ipynb).")
        return 1
    try:
        from ultralytics import YOLO
    except ImportError:
        print(
            "ultralytics is not installed in this environment. Use the croprow env:\n"
            "    croprow/.venv/Scripts/python croprow_disease/export_onnx.py"
        )
        return 1

    model = YOLO(str(PT))

    # Guard the class contract: exporting a single-class checkpoint under this
    # name would produce an ONNX that silently disagrees with every consumer.
    names = list(getattr(model, "names", {}).values()) or []
    if names and [str(n) for n in names] != CLASS_NAMES:
        print(f"Refusing to export: checkpoint classes are {names}, expected "
              f"{CLASS_NAMES}. Wrong weights, or a dataset yaml with the classes "
              "in the wrong order.")
        return 1

    # opset 12 + fixed imgsz keeps the export compatible with onnxruntime-web.
    out = model.export(format="onnx", imgsz=IMGSZ, opset=12, simplify=True)
    dest = HERE / "models" / "best.onnx"
    exported = Path(out)
    if exported.resolve() != dest.resolve():
        dest.write_bytes(exported.read_bytes())
    print(f"Wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB).")
    print(f"Output layout: 4 box + {len(CLASS_NAMES)} class scores per "
          f"prediction, class order {CLASS_NAMES}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
