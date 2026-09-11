"""CropHealth lab: two-class decode through a genuine ONNX Runtime session.

Mirrors `test_onnx_integration.py`, against the two-class head instead of the
potato taxonomy. The bug this file exists to catch is the one
`croprow_disease/export_onnx.py` warns about in its docstring: a serving path
written for the single-class croprow model reads 5 values per prediction where
this model has 6, and does not error, it just silently mislabels. So the
assertions here are specifically about *which class* each box came back as, not
merely that boxes came back.

Skipped automatically when onnx/onnxruntime are not installed, so the suite
still runs on a minimal install.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.services.crophealth_detector import CLASS_NAMES, CropHealthDetector

onnx = pytest.importorskip("onnx", reason="onnx not installed")
ort = pytest.importorskip("onnxruntime", reason="onnxruntime not installed")

N_CLASSES = 2
N_ANCHORS = 64
# The trained checkpoint spells them capitalised; serving lower-cases them.
TRAINED_NAMES = ["Healthy", "Unhealthy"]


def build_health_onnx(path, boxes, names: list[str] | None = TRAINED_NAMES):
    """An ONNX graph shaped exactly like the croprow_disease export.

    Input  : images  float32 (1, 3, 640, 640)
    Output : output0 float32 (1, 4+2, N)

    The graph ignores the image and emits a constant prediction tensor: this is
    a test of the serving decoder, not of a trained network. `boxes` entries are
    ``(cx, cy, w, h, class_id, confidence)`` in letterboxed 640 space.
    """
    from onnx import TensorProto, helper, numpy_helper

    preds = np.zeros((N_ANCHORS, 4 + N_CLASSES), dtype=np.float32)
    preds[:, 4:] = 0.01  # background noise, below any threshold
    for i, (cx, cy, w, h, cls_id, conf) in enumerate(boxes):
        preds[i, :4] = [cx, cy, w, h]
        preds[i, 4:] = 0.01
        preds[i, 4 + cls_id] = conf

    const = numpy_helper.from_array(preds.T[None, ...].copy(), name="pred_const")
    node = helper.make_node("Identity", inputs=["pred_const"], outputs=["output0"])
    graph = helper.make_graph(
        nodes=[node],
        name="health_like",
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
    if names is not None:
        # Ultralytics writes class names into ONNX metadata as a dict repr.
        entry = model.metadata_props.add()
        entry.key = "names"
        entry.value = repr({i: n for i, n in enumerate(names)})
    onnx.save(model, str(path))
    return path


@pytest.fixture
def frame_640x480():
    """An RGB frame, as the router hands it over: 640x480 letterboxes to 640
    with scale 1.0 and an 80px vertical pad, so expected pixels are easy to
    state by hand."""
    return np.asarray(Image.new("RGB", (640, 480), (80, 120, 70)))


def load(onnx_path) -> CropHealthDetector:
    det = CropHealthDetector()
    det._loaded = True  # skip the lazy path so the test picks the weights
    det._load_onnx(onnx_path)
    return det


def test_class_names_are_read_from_metadata_and_lower_cased(tmp_path):
    path = build_health_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 100.0, 100.0, 0, 0.9)])
    det = load(path)

    assert det.available is True
    assert det.status()["classes"] == CLASS_NAMES  # 'Healthy' -> 'healthy'
    assert det.status()["class_mismatch"] is None
    assert det.status()["version"].startswith("onnx:")


def test_an_unhealthy_box_is_labelled_unhealthy(tmp_path, frame_640x480):
    """The six-values-per-prediction contract, asserted where it can break.

    Class 1 must come back as 'unhealthy'. A decoder that took a single
    objectness column would report the crop class for this box instead.
    """
    path = build_health_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 200.0, 100.0, 1, 0.88)])
    result = load(path).predict_array(frame_640x480)

    assert result.model_available is True
    assert len(result.detections) == 1
    d = result.detections[0]
    assert d["class_key"] == "unhealthy"
    assert d["confidence"] == pytest.approx(0.88, abs=1e-4)
    # 640x480 letterboxed to 640: scale 1.0, 80px vertical pad removed again.
    assert d["bbox_norm"] == pytest.approx([0.34375, 0.39583, 0.65625, 0.60417], abs=1e-3)


def test_a_healthy_box_is_labelled_healthy(tmp_path, frame_640x480):
    path = build_health_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 200.0, 100.0, 0, 0.77)])
    result = load(path).predict_array(frame_640x480)
    assert [d["class_key"] for d in result.detections] == ["healthy"]


def test_overlapping_healthy_and_unhealthy_both_survive(tmp_path, frame_640x480):
    """Suppression is per class, matching the browser decoder.

    Pooling the classes would delete the lower-scoring of two overlapping boxes,
    which is exactly the case where the two labels disagree and the farmer most
    needs to see both.
    """
    path = build_health_onnx(
        tmp_path / "m.onnx",
        [
            (200.0, 300.0, 120.0, 120.0, 0, 0.75),
            (203.0, 302.0, 120.0, 120.0, 1, 0.82),  # overlaps, different class
            (500.0, 300.0, 90.0, 90.0, 1, 0.60),  # separate unhealthy plant
        ],
    )
    result = load(path).predict_array(frame_640x480)

    assert len(result.detections) == 3
    assert [d["class_key"] for d in result.detections] == ["unhealthy", "healthy", "unhealthy"]


def test_duplicate_boxes_of_one_class_are_suppressed(tmp_path, frame_640x480):
    path = build_health_onnx(
        tmp_path / "m.onnx",
        [
            (300.0, 300.0, 120.0, 120.0, 1, 0.80),
            (302.0, 301.0, 120.0, 120.0, 1, 0.70),  # same plant, same class
        ],
    )
    result = load(path).predict_array(frame_640x480)
    assert len(result.detections) == 1
    assert result.detections[0]["confidence"] == pytest.approx(0.80, abs=1e-4)


def test_weights_from_another_model_are_served_but_flagged(tmp_path, frame_640x480):
    """Boxes are real, labels are not. Report the mismatch rather than dressing
    an unrelated model's classes up as a health call."""
    path = build_health_onnx(
        tmp_path / "m.onnx", [(320.0, 320.0, 100.0, 100.0, 1, 0.9)], names=["weed", "lettuce"]
    )
    status = load(path).status()

    assert status["available"] is True
    assert status["classes"] == ["weed", "lettuce"]
    assert "not trustworthy" in status["class_mismatch"]


def test_missing_weights_report_unavailable_rather_than_guessing(tmp_path, frame_640x480):
    from app.config import settings as app_settings

    original = (app_settings.crophealth_onnx_path, app_settings.crophealth_pt_path)
    app_settings.crophealth_onnx_path = tmp_path / "absent.onnx"
    app_settings.crophealth_pt_path = tmp_path / "absent.pt"
    try:
        det = CropHealthDetector()
        result = det.predict_array(frame_640x480)
    finally:
        app_settings.crophealth_onnx_path, app_settings.crophealth_pt_path = original

    assert det.available is False
    assert result.model_available is False
    assert result.detections == []
    assert "export_onnx" in result.note


def test_nothing_above_threshold_is_an_empty_list_not_an_error(tmp_path, frame_640x480):
    path = build_health_onnx(tmp_path / "m.onnx", [(320.0, 320.0, 100.0, 100.0, 1, 0.05)])
    result = load(path).predict_array(frame_640x480)

    assert result.model_available is True
    assert result.detections == []
    assert "no plant" in result.note


class TestEndpoints:
    """The lab contract the browser is written against."""

    def test_status_and_thresholds_agree_on_the_class_list(self, client):
        status = client.get("/crophealth/status").json()
        thresholds = client.get("/crophealth/thresholds").json()

        assert thresholds["classes"] == status["classes"]
        assert thresholds["default"] == status["conf_threshold"]
        assert thresholds["iou_threshold"] == status["iou_threshold"]
        # No tuned per-class table exists for this model; shipping invented
        # numbers would make the two paths agree on a value neither measured.
        assert thresholds["per_class"] == {}

    def test_frame_rejects_a_non_image(self, client):
        r = client.post(
            "/crophealth/frame", files={"image": ("x.txt", b"not an image", "text/plain")}
        )
        assert r.status_code == 400

    def test_frame_rejects_an_empty_upload(self, client):
        r = client.post("/crophealth/frame", files={"image": ("x.jpg", b"", "image/jpeg")})
        assert r.status_code == 400

    def test_frame_returns_per_class_counts(self, client, tmp_path):
        from PIL import Image as PILImage

        path = tmp_path / "f.jpg"
        PILImage.new("RGB", (320, 240), (60, 120, 60)).save(path)
        r = client.post(
            "/crophealth/frame", files={"image": ("f.jpg", path.read_bytes(), "image/jpeg")}
        )
        assert r.status_code == 200
        body = r.json()
        # `counts` is the readout's whole input, so it has to be self-consistent
        # with the box list rather than something the UI must reconcile.
        assert sum(body["counts"].values()) == body["count"] == len(body["detections"])
        assert set(body["counts"]) == {d["class_key"] for d in body["detections"]}

    def test_frame_never_creates_a_case(self, client, tmp_path):
        """The lab is walled off from the /detect case flow: no case, no DB write."""
        from PIL import Image as PILImage

        path = tmp_path / "f.jpg"
        PILImage.new("RGB", (320, 240), (60, 120, 60)).save(path)
        before = len(client.get("/review/queue?limit=500").json())
        client.post("/crophealth/frame", files={"image": ("f.jpg", path.read_bytes(), "image/jpeg")})
        after = len(client.get("/review/queue?limit=500").json())
        assert before == after
