"""The class-order contract, enforced instead of merely documented.

`ml/data.yaml` carries a loud comment saying its class order must stay in
lockstep with `taxonomy.CLASS_NAMES`. A comment cannot fail a build. If the two
ever diverge, the model returns index 1 meaning "early blight" while the backend
reads index 1 as "late blight", and every downstream decision is confidently
wrong -- wrong pathogen named, wrong chemistry recommended, wrong disease
plotted on the officer's hotspot map. Nothing else in the pipeline can catch it,
because all the components agree with each other; they are simply all wrong.

These tests are that missing check.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.services import taxonomy
from app.services.detector import Detector

DATA_YAML = REPO_ROOT / "ml" / "data.yaml"


def parse_yaml_names(path: Path) -> list[str]:
    """Read the `names:` block without requiring PyYAML."""
    text = path.read_text(encoding="utf-8")
    block = re.search(r"^names:\s*$(.*)", text, re.M | re.S)
    assert block, f"no names: block in {path}"
    pairs: list[tuple[int, str]] = []
    for line in block.group(1).splitlines():
        m = re.match(r"^\s+(\d+):\s*(\S+)\s*$", line)
        if m:
            pairs.append((int(m.group(1)), m.group(2)))
        elif line.strip() and not line.startswith((" ", "\t")):
            break
    return [name for _, name in sorted(pairs)]


class TestDataYamlLockstep:
    def test_data_yaml_matches_taxonomy_exactly(self):
        """Order matters, not just membership."""
        assert parse_yaml_names(DATA_YAML) == list(taxonomy.CLASS_NAMES)

    def test_data_yaml_indices_are_contiguous_from_zero(self):
        names = parse_yaml_names(DATA_YAML)
        assert len(names) == 3
        assert len(set(names)) == 3

    def test_prepare_dataset_uses_the_same_order(self):
        """The dataset builder writes labels by index; it must agree too."""
        source = (REPO_ROOT / "ml" / "prepare_dataset.py").read_text(encoding="utf-8")
        m = re.search(r"^CLASS_NAMES = \[(.*?)\]", source, re.M | re.S)
        assert m
        names = re.findall(r'"([a-z_]+)"', m.group(1))
        assert names == list(taxonomy.CLASS_NAMES)

    def test_training_and_tuning_scripts_use_the_same_order(self):
        for script in ("train_yolo.py", "tune_thresholds.py", "export_feedback.py"):
            source = (REPO_ROOT / "ml" / script).read_text(encoding="utf-8")
            m = re.search(r"^CLASS_NAMES = \[(.*?)\]", source, re.M | re.S)
            assert m, f"{script} has no CLASS_NAMES"
            names = re.findall(r'"([a-z_]+)"', m.group(1))
            assert names == list(taxonomy.CLASS_NAMES), f"{script} is out of lockstep"


class TestDetectorLockstepCheck:
    """The runtime half: catch a mismatched checkpoint at load time."""

    def test_matching_order_raises_no_mismatch(self):
        d = Detector()
        d._check_class_lockstep(list(taxonomy.CLASS_NAMES))
        assert d._class_mismatch is None

    def test_swapped_order_is_detected(self):
        d = Detector()
        swapped = list(taxonomy.CLASS_NAMES)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        d._check_class_lockstep(swapped)
        assert d._class_mismatch is not None
        assert "ORDER MISMATCH" in d._class_mismatch

    def test_wrong_class_set_is_detected(self):
        d = Detector()
        d._check_class_lockstep(["tomato_blight", "corn_rust"])
        assert d._class_mismatch is not None
        assert "CLASS SET MISMATCH" in d._class_mismatch

    def test_mismatch_surfaces_in_status(self):
        d = Detector()
        d._loaded = True
        d._check_class_lockstep(["a", "b", "c"])
        assert d.status()["class_mismatch"] is not None

    def test_clean_detector_reports_no_mismatch(self):
        d = Detector()
        d._loaded = True
        assert d.status()["class_mismatch"] is None


class TestOnnxMetadataLockstep:
    """End to end: a real ONNX file whose embedded names are in the wrong order
    must be caught when it is loaded, not when a farmer gets bad advice."""

    @pytest.fixture
    def swapped_model(self, tmp_path):
        onnx = pytest.importorskip("onnx")
        import sys

        sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))
        from test_onnx_integration import build_yolo_like_onnx

        path = build_yolo_like_onnx(
            tmp_path / "swapped.onnx", [(320.0, 320.0, 200.0, 100.0, 1, 0.9)]
        )
        model = onnx.load(str(path))
        swapped = list(taxonomy.CLASS_NAMES)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        entry = model.metadata_props.add()
        entry.key = "names"
        entry.value = str({i: n for i, n in enumerate(swapped)})
        onnx.save(model, str(path))
        return path

    def test_swapped_onnx_metadata_is_caught_on_load(self, swapped_model, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "yolo_onnx_path", swapped_model)
        d = Detector()
        assert d.available
        assert d.status()["class_mismatch"] is not None
        assert "ORDER MISMATCH" in d.status()["class_mismatch"]
