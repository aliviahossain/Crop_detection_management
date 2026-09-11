"""Two-class plant-health detector (healthy / unhealthy) for the CropHealth lab.

Third detector in the repo, and deliberately a third file. ``detector.py`` is
the potato disease model with its own taxonomy; ``croprow_detector.py`` is the
single-class crop localizer. This one localizes crop plants *and* calls each one
healthy or unhealthy, from the weights trained in ``../croprow_disease/``.

The difference from croprow that actually matters at decode time: this model
emits **4 box + 2 class scores** per prediction rather than 4 + 1, so a box is
classified by the argmax of the two class columns instead of being labelled with
a single fixed class name. Suppression is therefore run **per class**, matching
``frontend/src/lib/yoloDecode.js`` -- a healthy and an unhealthy plant that
overlap are two findings, not one, and pooling them would silently delete the
lower-scoring class.

Serving prefers the ONNX export (numpy, torch-free, and the very same file the
browser runs on-device); ``best.pt`` via ultralytics is the training-time
fallback. With neither present the detector reports itself unavailable rather
than inventing boxes.

What this does *not* claim: the training labels came from a colour rule over
real annotation polygons (see ``croprow_disease/health.py``), not from an
agronomist. This is crop-vigour triage, not a disease diagnosis, and the lab UI
says so.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.config import settings
from app.services.detector import _letterbox, _nms

log = logging.getLogger(__name__)

INPUT_SIZE = 640
HEALTHY = "healthy"
UNHEALTHY = "unhealthy"
# Index order is the model's own class order, and must stay in lockstep with
# croprow_disease/health.py CLASS_NAMES. Reordering here mislabels every box.
CLASS_NAMES = [HEALTHY, UNHEALTHY]

MISSING_WEIGHTS_NOTE = (
    "No crop-health weights found. Export the trained model with "
    "`python croprow_disease/export_onnx.py` (writes croprow_disease/models/best.onnx), "
    "or place best.pt in croprow_disease/models/. Until then the CropHealth lab "
    "reports no detections instead of guessing."
)


@dataclass
class CropHealthResult:
    model_available: bool
    model_version: str | None
    detections: list[dict] = field(default_factory=list)  # {class_key, confidence, bbox_norm}
    image_size: tuple[int, int] | None = None
    note: str | None = None


class CropHealthDetector:
    """Lazy-loading, thread-safe wrapper around the croprow_disease weights."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._session = None  # onnxruntime.InferenceSession
        self._pt_model = None  # ultralytics.YOLO
        self._input_name: str | None = None
        self._class_names: list[str] = list(CLASS_NAMES)
        self._version: str | None = None
        self._note: str | None = None
        self._class_mismatch: str | None = None

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            onnx_path = Path(settings.crophealth_onnx_path)
            pt_path = Path(settings.crophealth_pt_path)
            if onnx_path.exists():
                self._load_onnx(onnx_path)
            elif pt_path.exists():
                self._load_pt(pt_path)
            else:
                self._note = MISSING_WEIGHTS_NOTE
                log.warning(self._note)
            self._loaded = True

    def _load_onnx(self, path: Path) -> None:
        try:
            import onnxruntime as ort
        except ImportError:
            self._note = f"Found {path} but onnxruntime is not installed in this environment."
            log.warning(self._note)
            return
        self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        meta = self._session.get_modelmeta().custom_metadata_map or {}
        self._adopt_names(self._parse_names(meta.get("names")))
        self._version = f"onnx:{path.name}"
        log.info("Loaded CropHealth ONNX %s with classes %s", path.name, self._class_names)

    def _load_pt(self, path: Path) -> None:
        try:
            from ultralytics import YOLO
        except ImportError:
            self._note = (
                f"Found {path} but ultralytics is not installed. Export to ONNX with "
                "`python croprow_disease/export_onnx.py` so serving stays torch-free."
            )
            log.warning(self._note)
            return
        self._pt_model = YOLO(str(path))
        names = getattr(self._pt_model, "names", None)
        if isinstance(names, dict):
            self._adopt_names([str(names[k]) for k in sorted(names)])
        self._version = f"pt:{path.name}"
        log.info("Loaded CropHealth .pt %s with classes %s", path.name, self._class_names)

    def _adopt_names(self, names: list[str] | None) -> None:
        """Take the model's own class list, lower-cased, and flag a mismatch.

        The trained checkpoint spells its classes ``Healthy``/``Unhealthy``;
        everything downstream (the UI colours, the per-class counters) keys off
        the lower-case names, so normalise here rather than at every use site. A
        model whose classes are not this two-class health pair is still served --
        the boxes are real -- but the mismatch is reported so nobody reads
        "unhealthy" off a model that was never trained to say it.
        """
        if not names:
            return
        self._class_names = [n.strip().lower() for n in names]
        if self._class_names != CLASS_NAMES:
            self._class_mismatch = (
                f"Loaded weights expose classes {self._class_names}, expected {CLASS_NAMES}. "
                "Boxes are still real, but the health labels on them are not trustworthy."
            )
            log.warning(self._class_mismatch)

    @staticmethod
    def _parse_names(raw: str | None) -> list[str] | None:
        if not raw:
            return None
        import ast

        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return None
        if isinstance(parsed, dict):
            return [str(parsed[k]) for k in sorted(parsed)]
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return None

    # ------------------------------------------------------------------
    # public surface
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        self._load()
        return self._session is not None or self._pt_model is not None

    def status(self) -> dict:
        self._load()
        return {
            "available": self.available,
            "version": self._version,
            "classes": self._class_names,
            "conf_threshold": settings.crophealth_conf_threshold,
            "iou_threshold": settings.crophealth_iou_threshold,
            "class_mismatch": self._class_mismatch,
            "note": self._note,
        }

    def predict_array(self, arr: np.ndarray) -> CropHealthResult:
        """Run inference on an RGB numpy frame. No disk I/O -- live frames are
        throughput, not evidence."""
        self._load()
        if not self.available:
            return CropHealthResult(model_available=False, model_version=None, note=self._note)

        h, w = arr.shape[:2]
        dets = self._infer_onnx(arr) if self._session is not None else self._infer_pt(arr)
        dets.sort(key=lambda d: d["confidence"], reverse=True)
        for d in dets:
            x1, y1, x2, y2 = d.pop("_bbox")
            d["bbox_norm"] = [
                round(x1 / w, 5),
                round(y1 / h, 5),
                round(x2 / w, 5),
                round(y2 / h, 5),
            ]
        return CropHealthResult(
            model_available=True,
            model_version=self._version,
            detections=dets,
            image_size=(w, h),
            note=None if dets else "Model ran but found no plant above the confidence threshold.",
        )

    def _class_key(self, index: int) -> str:
        """Class name for a head index, never an IndexError.

        A model with more class columns than advertised names would otherwise
        crash the lab preview; naming the index is honest and keeps it running.
        """
        if 0 <= index < len(self._class_names):
            return self._class_names[index]
        return f"class_{index}"

    # ------------------------------------------------------------------
    # inference
    # ------------------------------------------------------------------
    def _infer_onnx(self, arr: np.ndarray) -> list[dict]:
        canvas, scale, pad_x, pad_y = _letterbox(arr, INPUT_SIZE)
        blob = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self._session.run(None, {self._input_name: blob})[0]
        preds = out[0] if out.ndim == 3 else np.squeeze(out)
        if preds.ndim != 2:
            return []
        preds = self._orient(preds)
        n_cls = preds.shape[1] - 4
        if n_cls <= 0:
            return []

        scores_all = preds[:, 4 : 4 + n_cls]
        class_ids = scores_all.argmax(axis=1)
        confs = scores_all.max(axis=1)
        keep_mask = confs >= settings.crophealth_conf_threshold
        if not keep_mask.any():
            return []
        boxes_cxcywh = preds[keep_mask, :4]
        class_ids = class_ids[keep_mask]
        confs = confs[keep_mask]

        cx, cy, bw, bh = boxes_cxcywh.T
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - pad_x) / scale
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - pad_y) / scale
        h, w = arr.shape[:2]
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clip(0, w)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clip(0, h)

        # Per class, like the browser decoder: a healthy and an unhealthy plant
        # that overlap must both survive.
        results: list[dict] = []
        for cid in np.unique(class_ids):
            sel = np.flatnonzero(class_ids == cid)
            for local in _nms(xyxy[sel], confs[sel], settings.crophealth_iou_threshold):
                idx = int(sel[local])
                results.append(
                    {
                        "class_key": self._class_key(int(cid)),
                        "confidence": round(float(confs[idx]), 4),
                        "_bbox": [float(v) for v in xyxy[idx]],
                    }
                )
        return results

    def _orient(self, preds: np.ndarray) -> np.ndarray:
        """Return predictions as (num_anchors, 4 + num_classes). A detect head
        always has far more anchors than channels, so orient on that."""
        expected = 4 + len(self._class_names)
        if preds.shape[0] == expected and preds.shape[1] != expected:
            return preds.T
        if preds.shape[1] == expected:
            return preds
        return preds.T if preds.shape[0] < preds.shape[1] else preds

    def _infer_pt(self, arr: np.ndarray) -> list[dict]:
        res = self._pt_model.predict(
            source=arr,
            conf=settings.crophealth_conf_threshold,
            iou=settings.crophealth_iou_threshold,
            verbose=False,
        )[0]
        out: list[dict] = []
        for b in res.boxes:
            out.append(
                {
                    "class_key": self._class_key(int(b.cls.item())),
                    "confidence": round(float(b.conf.item()), 4),
                    "_bbox": [float(v) for v in b.xyxy[0].tolist()],
                }
            )
        return out


crophealth_detector = CropHealthDetector()
