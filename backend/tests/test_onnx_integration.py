"""Decode a genuine ONNX Runtime session, not a stub.

`test_detector.py` exercises the decoding maths against a fake session. That
catches maths bugs but would not catch an integration bug: a wrong input name,
metadata that fails to parse, a dtype mismatch, or an onnxruntime version whose
output layout differs. This module builds a real ONNX graph with the YOLOv8
detect output signature, runs it through onnxruntime, and asserts the serving
layer decodes it correctly end to end.

Skipped automatically when onnx/onnxruntime are not installed, so the suite
still runs on a minimal install.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.services import taxonomy
from app.services.detector import Detector

onnx = pytest.importorskip("onnx", reason="onnx not installed")
ort = pytest.importorskip("onnxruntime", reason="onnxruntime not installed")

N_CLASSES = len(taxonomy.CLASS_NAMES)
N_ANCHORS = 64  # small but realistic in layout: (1, 4+nc, N)


def build_yolo_like_onnx(path, boxes, with_metadata: bool = True):
    """An ONNX graph shaped exactly like a YOLOv8 detect export.

    Input  : images  float32 (1, 3, 640, 640)
    Output : output0 float32 (1, 4+nc, N)

    The graph ignores the image and emits a constant prediction tensor -- we are
    testing the serving decoder, not a trained network. Everything the decoder
    touches (shape, dtype, names, metadata) matches a real export.
    """
    from onnx import TensorProto, helper, numpy_helper

    preds = np.zeros((N_ANCHORS, 4 + N_CLASSES), dtype=np.float32)
    preds[:, 4:] = 0.01  # background noise
    for i, (cx, cy, w, h, cls_id, conf) in enumerate(boxes):
        preds[i, :4] = [cx, cy, w, h]
        preds[i, 4:] = 0.01
        preds[i, 4 + cls_id] = conf

    const = numpy_helper.from_array(preds.T[None, ...].copy(), name="pred_const")
    node = helper.make_node("Identity", inputs=["pred_const"], outputs=["output0"])
    graph = helper.make_graph(
        nodes=[node],
        name="yolo_like",
        inputs=[helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
        outputs=[
            helper.make_tensor_value_info(
                "output0", TensorProto.FLOAT, [1, 4 + N_CLASSES, N_ANCHORS]
            )
        ],
        initializer=[const],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 12)], producer_name="test"
    )
    model.ir_version = 8  # onnxruntime rejects newer IR versions than it knows
    if with_metadata:
        # Ultralytics writes class names into ONNX metadata as a dict repr.
        entry = model.metadata_props.add()
        entry.key = "names"
        entry.value = repr({i: n for i, n in enumerate(taxonomy.CLASS_NAMES)})
    onnx.save(model, str(path))
    return path


@pytest.fixture
def image_640x480(tmp_path):
    path = tmp_path / "field.jpg"
    Image.new("RGB", (640, 480), (80, 120, 70)).save(path)
    return path


def load_detector(onnx_path) -> Detector:
    det = Detector()
    det._loaded = True
    det._load_onnx(onnx_path)
    det._load_thresholds()
    return det


def test_real_session_loads_and_reads_class_names(tmp_path, image_640x480):
    path = build_yolo_like_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 200.0, 100.0, 1, 0.88)])
    det = load_detector(path)

    assert det.available is True
    assert det.class_names == taxonomy.CLASS_NAMES  # parsed out of ONNX metadata
    assert det.version.startswith("onnx:")


def test_real_session_decodes_into_image_coordinates(tmp_path, image_640x480):
    """Same expectation as the fake-session test, now through onnxruntime."""
    path = build_yolo_like_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 200.0, 100.0, 1, 0.88)])
    result = load_detector(path).predict(image_640x480)

    assert result.model_available is True
    assert result.top_class == "potato_late_blight"
    assert result.top_confidence == pytest.approx(0.88, abs=1e-4)
    d = result.detections[0]
    # 640x480 letterboxed to 640: scale 1.0, 80px vertical pad.
    assert d.bbox == pytest.approx([220.0, 190.0, 420.0, 290.0], abs=0.5)
    assert d.bbox_norm == pytest.approx([0.34375, 0.39583, 0.65625, 0.60417], abs=1e-3)


def test_real_session_without_metadata_falls_back_to_taxonomy_order(tmp_path, image_640x480):
    path = build_yolo_like_onnx(
        tmp_path / "m.onnx", [(320.0, 320.0, 100.0, 100.0, 0, 0.9)], with_metadata=False
    )
    det = load_detector(path)
    assert det.class_names == taxonomy.CLASS_NAMES
    assert det.predict(image_640x480).top_class == "potato_early_blight"


def test_real_session_applies_tuned_per_class_thresholds(tmp_path, image_640x480):
    import json

    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(
        json.dumps({"per_class": {"potato_late_blight": 0.10, "potato_healthy": 0.80}}),
        encoding="utf-8",
    )
    path = build_yolo_like_onnx(
        tmp_path / "m.onnx",
        [
            (200.0, 320.0, 80.0, 80.0, 1, 0.14),  # faint late blight -> kept at 0.10
            (450.0, 320.0, 80.0, 80.0, 2, 0.55),  # unsure healthy    -> dropped at 0.80
        ],
    )
    from app.config import settings as app_settings

    original = app_settings.detection_thresholds_path
    app_settings.detection_thresholds_path = thresholds
    try:
        result = load_detector(path).predict(image_640x480)
    finally:
        app_settings.detection_thresholds_path = original

    keys = {d.class_key for d in result.detections}
    assert keys == {"potato_late_blight"}, (
        "the faint late blight must survive its lowered threshold and the unsure "
        "healthy call must be suppressed by its raised one"
    )


def test_real_session_multiple_classes_survive_nms(tmp_path, image_640x480):
    path = build_yolo_like_onnx(
        tmp_path / "m.onnx",
        [
            (200.0, 300.0, 120.0, 120.0, 0, 0.75),
            (203.0, 302.0, 120.0, 120.0, 1, 0.82),  # overlaps, different class
            (500.0, 300.0, 90.0, 90.0, 1, 0.60),  # separate late blight lesion
        ],
    )
    result = load_detector(path).predict(image_640x480)
    assert result.top_class == "potato_late_blight"
    assert len(result.detections) == 3  # per-class NMS keeps all three
