"""Tests for the ONNX output decoder.

This is the riskiest code in the serving layer: if the letterbox inverse or the
class-index mapping is wrong, the API still returns 200 and the boxes are
quietly in the wrong place. A fake InferenceSession lets us assert exact
coordinates without needing a trained model or an onnx dependency in CI.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.services import taxonomy
from app.services.detector import Detector, _nms


class FakeSession:
    """Stands in for onnxruntime.InferenceSession, returning a fixed tensor."""

    def __init__(self, output: np.ndarray):
        self._output = output

    def get_inputs(self):
        class _Input:
            name = "images"

        return [_Input()]

    def run(self, _outputs, _feed):
        return [self._output]


def make_detector(output: np.ndarray) -> Detector:
    det = Detector()
    det._loaded = True
    det._session = FakeSession(output)
    det._input_name = "images"
    det._class_names = list(taxonomy.CLASS_NAMES)
    det._version = "test"
    return det


def yolo_output(boxes: list[tuple[float, float, float, float, int, float]], n_cls: int = 3):
    """Build a (1, 4+n_cls, N) YOLOv8-style detect tensor."""
    rows = []
    for cx, cy, w, h, cls_id, conf in boxes:
        scores = [0.01] * n_cls
        scores[cls_id] = conf
        rows.append([cx, cy, w, h, *scores])
    return np.array(rows, dtype=np.float32).T[None, ...]


@pytest.fixture
def landscape_image(tmp_path):
    """640x480 -- wider than tall, so letterboxing pads top and bottom."""
    path = tmp_path / "leaf.jpg"
    Image.new("RGB", (640, 480), (70, 110, 70)).save(path)
    return path


def test_decodes_box_back_into_original_image_coordinates(landscape_image):
    # 640x480 -> scale 1.0, vertical pad of 80px top and bottom.
    det = make_detector(yolo_output([(320.0, 320.0, 200.0, 100.0, 1, 0.9)]))
    result = det.predict(landscape_image)

    assert result.model_available is True
    assert len(result.detections) == 1
    d = result.detections[0]
    assert d.class_key == "potato_late_blight"  # index 1
    assert d.confidence == pytest.approx(0.9, abs=1e-4)
    assert d.bbox == pytest.approx([220.0, 190.0, 420.0, 290.0], abs=0.5)
    assert d.bbox_norm == pytest.approx([0.34375, 0.39583, 0.65625, 0.60417], abs=1e-3)


def test_class_index_maps_through_the_taxonomy_order(landscape_image):
    for idx, expected in enumerate(taxonomy.CLASS_NAMES):
        det = make_detector(yolo_output([(320.0, 320.0, 100.0, 100.0, idx, 0.8)]))
        assert det.predict(landscape_image).top_class == expected


def test_low_confidence_predictions_are_filtered_out(landscape_image):
    # Default conf threshold is 0.25.
    det = make_detector(yolo_output([(320.0, 320.0, 100.0, 100.0, 0, 0.10)]))
    result = det.predict(landscape_image)
    assert result.detections == []
    assert result.top_class is None
    assert "no symptom" in (result.note or "").lower()


def test_overlapping_boxes_of_one_class_are_suppressed(landscape_image):
    det = make_detector(
        yolo_output(
            [
                (320.0, 320.0, 200.0, 200.0, 0, 0.90),
                (325.0, 322.0, 200.0, 200.0, 0, 0.70),  # heavy overlap, lower score
            ]
        )
    )
    assert len(det.predict(landscape_image).detections) == 1


def test_distinct_classes_both_survive_nms(landscape_image):
    # NMS runs per class, so a co-located early and late blight box both stand.
    det = make_detector(
        yolo_output(
            [
                (320.0, 320.0, 200.0, 200.0, 0, 0.90),
                (322.0, 321.0, 200.0, 200.0, 1, 0.85),
            ]
        )
    )
    result = det.predict(landscape_image)
    assert {d.class_key for d in result.detections} == {
        "potato_early_blight",
        "potato_late_blight",
    }


def test_top_detection_is_the_most_confident(landscape_image):
    det = make_detector(
        yolo_output(
            [
                (100.0, 320.0, 60.0, 60.0, 0, 0.55),
                (500.0, 320.0, 60.0, 60.0, 1, 0.88),
            ]
        )
    )
    result = det.predict(landscape_image)
    assert result.top_class == "potato_late_blight"
    assert result.top_confidence == pytest.approx(0.88, abs=1e-4)


def test_boxes_are_clipped_to_the_image(landscape_image):
    # A box running off the left edge must not produce a negative coordinate.
    det = make_detector(yolo_output([(10.0, 320.0, 200.0, 100.0, 0, 0.9)]))
    d = det.predict(landscape_image).detections[0]
    assert d.bbox[0] >= 0
    assert d.bbox[2] <= 640


def test_handles_a_realistic_anchor_count(landscape_image):
    """A real 640px YOLOv8 head emits 8400 anchors, nearly all background."""
    rng = np.random.default_rng(0)
    n_cls = len(taxonomy.CLASS_NAMES)
    anchors = np.zeros((8400, 4 + n_cls), dtype=np.float32)
    anchors[:, :4] = rng.uniform(50, 550, size=(8400, 4))
    anchors[:, 4:] = rng.uniform(0.0, 0.05, size=(8400, n_cls))  # background noise
    anchors[4200] = [320.0, 320.0, 200.0, 100.0, 0.02, 0.02, 0.93]  # one real hit

    det = make_detector(anchors.T[None, ...])  # (1, 4+nc, 8400), the export layout
    result = det.predict(landscape_image)
    assert result.top_class == "potato_healthy"  # index 2
    assert result.top_confidence == pytest.approx(0.93, abs=1e-4)
    assert result.detections[0].bbox == pytest.approx([220.0, 190.0, 420.0, 290.0], abs=0.5)


def test_missing_weights_reports_unavailable_rather_than_guessing(landscape_image):
    det = Detector()  # no weights on disk in the test environment
    result = det.predict(landscape_image)
    assert result.model_available is False
    assert result.top_class is None
    assert "no trained weights" in (result.note or "").lower()


class TestPerClassThresholds:
    """Tuned thresholds encode the asymmetric cost of a miss vs a false alarm."""

    def _tuned(self, tmp_path, per_class: dict) -> Detector:
        import json

        path = tmp_path / "thresholds.json"
        path.write_text(json.dumps({"per_class": per_class, "default": 0.25}), encoding="utf-8")
        det = Detector()
        det._loaded = True
        det._class_names = list(taxonomy.CLASS_NAMES)
        from app.config import settings as app_settings

        original = app_settings.detection_thresholds_path
        app_settings.detection_thresholds_path = path
        try:
            det._load_thresholds()
        finally:
            app_settings.detection_thresholds_path = original
        return det

    def test_falls_back_to_the_env_default_when_untuned(self):
        det = Detector()
        det._load_thresholds()
        assert det.threshold_for("potato_late_blight") == pytest.approx(0.25)
        assert det.status()["threshold_source"]["source"] == "env_default"

    def test_tuned_thresholds_are_applied_per_class(self, tmp_path):
        det = self._tuned(tmp_path, {"potato_late_blight": 0.12, "potato_healthy": 0.7})
        assert det.threshold_for("potato_late_blight") == pytest.approx(0.12)
        assert det.threshold_for("potato_healthy") == pytest.approx(0.7)
        # A class absent from the file keeps the env default.
        assert det.threshold_for("potato_early_blight") == pytest.approx(0.25)

    def test_a_low_threshold_keeps_a_faint_late_blight_detection(
        self, tmp_path, landscape_image
    ):
        """A 0.15-confidence late blight box survives a 0.12 threshold.

        This is the whole point of tuning: at the stock 0.25 this detection is
        dropped and the farmer is told nothing is wrong.
        """
        det = self._tuned(tmp_path, {"potato_late_blight": 0.12})
        det._session = FakeSession(yolo_output([(320.0, 320.0, 100.0, 100.0, 1, 0.15)]))
        det._input_name = "images"
        det._version = "test"
        assert det.predict(landscape_image).top_class == "potato_late_blight"

    def test_a_high_threshold_suppresses_an_unsure_healthy_call(
        self, tmp_path, landscape_image
    ):
        """Saying 'healthy' at 0.5 confidence is how delayed treatment happens."""
        det = self._tuned(tmp_path, {"potato_healthy": 0.75})
        det._session = FakeSession(yolo_output([(320.0, 320.0, 100.0, 100.0, 2, 0.50)]))
        det._input_name = "images"
        det._version = "test"
        assert det.predict(landscape_image).detections == []


class TestNMS:
    def test_empty_input(self):
        assert _nms(np.zeros((0, 4)), np.zeros(0), 0.5) == []

    def test_keeps_the_higher_scoring_of_two_overlapping_boxes(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11]], dtype=float)
        assert _nms(boxes, np.array([0.6, 0.9]), 0.5) == [1]

    def test_keeps_both_when_they_do_not_overlap(self):
        boxes = np.array([[0, 0, 10, 10], [50, 50, 60, 60]], dtype=float)
        assert sorted(_nms(boxes, np.array([0.9, 0.8]), 0.5)) == [0, 1]
