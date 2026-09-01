"""YOLO inference for the serving layer.

Serving path is ONNX + onnxruntime on CPU: the dev laptop never installs
torch, inference is a few hundred ms per image, and the same artifact is what
an offline / on-device build would ship. A raw `.pt` via ultralytics is
supported as a fallback for whoever just finished training and has not
exported yet.

If no weights are present the detector reports itself unavailable rather than
inventing a prediction. The API then routes the case straight to the expert
review queue, which is the correct real-world behaviour and keeps the demo
honest.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from app.config import settings
from app.services import taxonomy

log = logging.getLogger(__name__)

INPUT_SIZE = 640


@dataclass
class Detection:
    class_key: str
    confidence: float
    bbox: list[float]  # [x1, y1, x2, y2] in original image pixels
    bbox_norm: list[float]  # same, normalised 0-1 (the frontend draws from this)


@dataclass
class DetectionResult:
    model_available: bool
    model_version: str | None
    detections: list[Detection] = field(default_factory=list)
    top_class: str | None = None
    top_confidence: float | None = None
    image_size: tuple[int, int] | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["detections"] = [
            d if isinstance(d, dict) else asdict(d) for d in self.detections
        ]
        return data


def _letterbox(img: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, float, int, int]:
    """Resize preserving aspect ratio, pad to square with grey (YOLO convention)."""
    h, w = img.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = np.asarray(Image.fromarray(img).resize((nw, nh), Image.BILINEAR))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top : top + nh, left : left + nw] = resized
    return canvas, scale, left, top


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Greedy non-max suppression. Pure numpy so serving stays torch-free."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


class Detector:
    """Lazy-loading, thread-safe wrapper around the trained potato model."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._session = None  # onnxruntime.InferenceSession
        self._pt_model = None  # ultralytics.YOLO
        self._input_name: str | None = None
        self._class_names: list[str] = list(taxonomy.CLASS_NAMES)
        self._version: str | None = None
        self._note: str | None = None
        self._thresholds: dict[str, float] = {}
        self._threshold_meta: dict = {}
        self._class_mismatch: str | None = None

    # ------------------------------------------------------------------
    # confidence thresholds
    # ------------------------------------------------------------------
    def _load_thresholds(self) -> None:
        """Per-class thresholds tuned by ml/tune_thresholds.py.

        A single 0.25 for every class assumes a false positive and a false
        negative cost the same. They do not: missing late blight can cost the
        field, while a false positive is caught downstream by the triage layer.
        When the tuned file is absent we fall back to the env default and say so.
        """
        path = Path(settings.detection_thresholds_path)
        if not path.exists():
            self._threshold_meta = {
                "source": "env_default",
                "note": (
                    "Using a single DETECTION_CONF_THRESHOLD for every class. Run "
                    "ml/tune_thresholds.py after training to tune per-class thresholds "
                    "against the asymmetric cost of a missed detection."
                ),
            }
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            per_class = data.get("per_class") or {}
            self._thresholds = {str(k): float(v) for k, v in per_class.items()}
            self._threshold_meta = {
                "source": str(path),
                "tuned_at": data.get("tuned_at"),
                "val_images": data.get("val_images"),
                "rationale": data.get("rationale"),
                "metrics": data.get("metrics"),
            }
            log.info("Loaded tuned per-class thresholds: %s", self._thresholds)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Could not read %s (%s); using the env default threshold", path, exc)
            self._threshold_meta = {"source": "env_default", "error": str(exc)}

    def threshold_for(self, class_name: str) -> float:
        return self._thresholds.get(class_name, settings.detection_conf_threshold)

    def _threshold_vector(self) -> np.ndarray:
        return np.array(
            [self.threshold_for(name) for name in self._class_names], dtype=np.float32
        )

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            onnx_path = Path(settings.yolo_onnx_path)
            pt_path = Path(settings.yolo_pt_path)
            if onnx_path.exists():
                self._load_onnx(onnx_path)
            elif pt_path.exists():
                self._load_pt(pt_path)
            else:
                self._note = (
                    "No trained weights found. Train on Kaggle (see ml/notebooks/) and place "
                    f"best.onnx at {onnx_path}. Until then every image case is routed to the "
                    "expert review queue instead of getting a guessed diagnosis."
                )
                log.warning(self._note)
            self._load_thresholds()
            self._loaded = True

    def _load_onnx(self, path: Path) -> None:
        import onnxruntime as ort

        self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        meta = self._session.get_modelmeta().custom_metadata_map or {}
        names_raw = meta.get("names")
        if names_raw:
            parsed = self._parse_names(names_raw)
            if parsed:
                self._class_names = parsed
                self._check_class_lockstep(parsed)
        self._version = f"onnx:{path.name}"
        log.info("Loaded ONNX detector %s with classes %s", path.name, self._class_names)

    def _check_class_lockstep(self, model_names: list[str]) -> None:
        """Verify the model's class order matches the taxonomy the app reasons with.

        This is the worst failure mode in the system. If `data.yaml` listed the
        classes in a different order than `taxonomy.CLASS_NAMES`, the model
        returns index 1 meaning "early blight" while the backend reads index 1 as
        "late blight" -- and every downstream decision is confidently wrong: the
        advisory names the wrong pathogen, recommends the wrong chemistry, and
        the hotspot map attributes an outbreak to the wrong disease. Nothing
        else in the pipeline can detect it, because every component agrees with
        every other; they are just all wrong together.

        Comparing the names embedded in the checkpoint against the taxonomy
        catches it at load time instead of in the field.
        """
        expected = list(taxonomy.CLASS_NAMES)
        if model_names == expected:
            self._class_mismatch = None
            return

        if sorted(model_names) == sorted(expected):
            detail = (
                f"ORDER MISMATCH: model class order {model_names} vs taxonomy {expected}. "
                "Every prediction will be mislabelled. Retrain with data.yaml matching "
                "taxonomy.CLASS_NAMES, or fix the taxonomy order to match the checkpoint."
            )
        else:
            detail = (
                f"CLASS SET MISMATCH: model has {model_names}, taxonomy expects {expected}. "
                "The loaded weights were trained for a different label set."
            )
        self._class_mismatch = detail
        log.error("Detector class lockstep check FAILED. %s", detail)

    @staticmethod
    def _parse_names(raw: str) -> list[str] | None:
        """Ultralytics stores class names in ONNX metadata as a dict repr."""
        import ast

        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            log.warning("Could not parse class names from ONNX metadata; using taxonomy order")
            return None
        if isinstance(parsed, dict):
            return [str(parsed[k]) for k in sorted(parsed)]
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return None

    def _load_pt(self, path: Path) -> None:
        try:
            from ultralytics import YOLO
        except ImportError:
            self._note = (
                f"Found {path} but ultralytics is not installed. Either export to ONNX "
                "(python ml/export_onnx.py) or pip install -r backend/requirements-optional.txt"
            )
            log.warning(self._note)
            return
        self._pt_model = YOLO(str(path))
        names = getattr(self._pt_model, "names", None)
        if isinstance(names, dict):
            self._class_names = [str(names[k]) for k in sorted(names)]
            self._check_class_lockstep(self._class_names)
        self._version = f"pt:{path.name}"

    # ------------------------------------------------------------------
    # inference
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        self._load()
        return self._session is not None or self._pt_model is not None

    @property
    def version(self) -> str | None:
        self._load()
        return self._version

    @property
    def class_names(self) -> list[str]:
        self._load()
        return self._class_names

    def status(self) -> dict:
        self._load()
        return {
            "available": self.available,
            "version": self._version,
            "classes": self._class_names,
            "conf_threshold_default": settings.detection_conf_threshold,
            "conf_thresholds": {
                name: self.threshold_for(name) for name in self._class_names
            },
            "threshold_source": self._threshold_meta,
            "low_confidence_threshold": settings.low_confidence_threshold,
            "note": self._note,
            "class_mismatch": self._class_mismatch,
        }

    def predict(self, image_path: str | Path) -> DetectionResult:
        self._load()
        if not self.available:
            return DetectionResult(model_available=False, model_version=None, note=self._note)

        img = Image.open(image_path).convert("RGB")
        arr = np.asarray(img)
        h, w = arr.shape[:2]

        dets = self._infer_onnx(arr) if self._session is not None else self._infer_pt(image_path)
        dets.sort(key=lambda d: d.confidence, reverse=True)
        for d in dets:
            d.bbox_norm = [
                round(d.bbox[0] / w, 5),
                round(d.bbox[1] / h, 5),
                round(d.bbox[2] / w, 5),
                round(d.bbox[3] / h, 5),
            ]
        top = dets[0] if dets else None
        return DetectionResult(
            model_available=True,
            model_version=self._version,
            detections=dets,
            top_class=top.class_key if top else None,
            top_confidence=top.confidence if top else None,
            image_size=(w, h),
            note=None if dets else "Model ran but found no symptom above the confidence threshold.",
        )

    def _infer_onnx(self, arr: np.ndarray) -> list[Detection]:
        canvas, scale, pad_x, pad_y = _letterbox(arr)
        blob = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self._session.run(None, {self._input_name: blob})[0]
        # (batch, 4+nc, N) for YOLOv8 / v11 detect heads. Drop only the batch
        # dimension -- np.squeeze would also collapse the anchor axis when a
        # model returns a single box.
        preds = out[0] if out.ndim == 3 else np.squeeze(out)
        if preds.ndim != 2:
            return []
        preds = self._orient(preds)  # -> (N, 4+nc)
        n_cls = preds.shape[1] - 4
        if n_cls <= 0:
            return []

        boxes_cxcywh = preds[:, :4]
        scores_all = preds[:, 4 : 4 + n_cls]
        cls_ids = scores_all.argmax(axis=1)
        confs = scores_all.max(axis=1)
        # Each class carries its own threshold (see _load_thresholds).
        thresholds = self._threshold_vector()
        if len(thresholds) != n_cls:  # metadata disagreed with the taxonomy
            thresholds = np.full(n_cls, settings.detection_conf_threshold, dtype=np.float32)
        keep_mask = confs >= thresholds[cls_ids]
        if not keep_mask.any():
            return []
        boxes_cxcywh = boxes_cxcywh[keep_mask]
        cls_ids = cls_ids[keep_mask]
        confs = confs[keep_mask]

        cx, cy, bw, bh = boxes_cxcywh.T
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
        # undo the letterbox transform back into original-image pixels
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - pad_x) / scale
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - pad_y) / scale
        h, w = arr.shape[:2]
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clip(0, w)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clip(0, h)

        results: list[Detection] = []
        for cid in np.unique(cls_ids):
            mask = cls_ids == cid
            cls_boxes, cls_confs = xyxy[mask], confs[mask]
            for idx in _nms(cls_boxes, cls_confs, settings.detection_iou_threshold):
                results.append(
                    Detection(
                        class_key=self._label(int(cid)),
                        confidence=round(float(cls_confs[idx]), 4),
                        bbox=[round(float(v), 2) for v in cls_boxes[idx]],
                        bbox_norm=[],
                    )
                )
        return results

    def _orient(self, preds: np.ndarray) -> np.ndarray:
        """Return predictions as (num_anchors, 4 + num_classes).

        Ultralytics emits (4+nc, N) and some export toolchains emit (N, 4+nc).
        Match on the known class count first -- guessing from which dimension is
        larger silently mislabels everything if a model ever returns fewer
        anchors than channels.
        """
        expected = 4 + len(self._class_names)
        if preds.shape[0] == expected and preds.shape[1] != expected:
            return preds.T
        if preds.shape[1] == expected:
            return preds
        # Unknown class count (e.g. metadata missing): fall back to the shape
        # heuristic, since a detect head always has far more anchors than
        # channels.
        return preds.T if preds.shape[0] < preds.shape[1] else preds

    def _infer_pt(self, image_path: str | Path) -> list[Detection]:
        # Predict at the loosest threshold any class uses, then apply each
        # class's own cut-off -- ultralytics only accepts a single `conf`.
        floor = min(
            [settings.detection_conf_threshold, *self._thresholds.values()]
        ) if self._thresholds else settings.detection_conf_threshold
        res = self._pt_model.predict(
            source=str(image_path),
            conf=floor,
            iou=settings.detection_iou_threshold,
            verbose=False,
        )[0]
        out: list[Detection] = []
        for b in res.boxes:
            class_key = self._label(int(b.cls.item()))
            confidence = float(b.conf.item())
            if confidence < self.threshold_for(class_key):
                continue
            out.append(
                Detection(
                    class_key=class_key,
                    confidence=round(confidence, 4),
                    bbox=[round(float(v), 2) for v in b.xyxy[0].tolist()],
                    bbox_norm=[],
                )
            )
        return out

    def _label(self, idx: int) -> str:
        if 0 <= idx < len(self._class_names):
            return self._class_names[idx]
        return f"class_{idx}"


detector = Detector()
