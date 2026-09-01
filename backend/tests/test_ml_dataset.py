"""Regression tests for ml/prepare_dataset.py and ml/tune_thresholds.py.

Both of these had bugs that failed *silently* -- the run completed, printed a
plausible summary, and produced a corrupted or empty result. That class of bug
does not announce itself, so it gets tests.
"""
from __future__ import annotations

import sys

import pytest
from PIL import Image

from app.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "ml"))

import prepare_dataset as pd  # noqa: E402
import tune_thresholds as tt  # noqa: E402


class TestHashUnit:
    """The docstring promises [0,1). A 12-hex-char digest over an 11-F divisor
    returned values up to 16.0 -- harmless while only used for sorting, silent
    garbage the moment anyone writes a range comparison."""

    def test_stays_within_the_unit_interval(self):
        values = [pd.hash_unit(f"image_{i}.jpg") for i in range(20000)]
        assert min(values) >= 0.0
        assert max(values) < 1.0

    def test_is_deterministic(self):
        assert pd.hash_unit("leaf.jpg") == pd.hash_unit("leaf.jpg")

    def test_is_roughly_uniform(self):
        """Split quotas depend on this; a skewed hash skews the splits."""
        values = [pd.hash_unit(f"k{i}") for i in range(20000)]
        assert 0.47 < sum(values) / len(values) < 0.53
        # Each decile should hold roughly a tenth of the mass.
        for d in range(10):
            share = sum(1 for v in values if d / 10 <= v < (d + 1) / 10) / len(values)
            assert 0.07 < share < 0.13, f"decile {d} holds {share:.2%}"

    def test_supports_a_range_gate(self):
        """The use that the broken version would have silently corrupted."""
        selected = [i for i in range(10000) if pd.hash_unit(f"k{i}") < 0.8]
        assert 0.77 < len(selected) / 10000 < 0.83


class TestLabelPathResolution:
    """`str(path).replace("images", "labels")` corrupts any dataset whose parent
    directory contains the word "images" -- which is an entirely ordinary Kaggle
    input name. Every image was then skipped with no error at all."""

    @pytest.fixture
    def dataset(self, tmp_path):
        # The exact shape that triggered the bug.
        root = tmp_path / "potato-images"
        (root / "images" / "train").mkdir(parents=True)
        (root / "labels" / "train").mkdir(parents=True)
        for i in range(4):
            Image.new("RGB", (16, 16), (30, 90, 40)).save(
                root / "images" / "train" / f"leaf{i}.jpg"
            )
            (root / "labels" / "train" / f"leaf{i}.txt").write_text("1 0.5 0.5 0.4 0.4\n")
        return root

    def test_rewrites_only_the_last_images_component(self, dataset):
        img = dataset / "images" / "train" / "leaf0.jpg"
        resolved = pd._labels_dir_for(img)
        assert resolved == dataset / "labels" / "train"
        # The parent directory name must survive untouched.
        assert "potato-images" in str(resolved)
        assert "potato-labels" not in str(resolved)

    def test_finds_the_label_under_a_tricky_parent_name(self, dataset):
        img = dataset / "images" / "train" / "leaf0.jpg"
        assert pd._find_label(img, dataset) is not None

    def test_collect_annotated_returns_records_not_silence(self, dataset):
        records = pd.collect_annotated(dataset, None)
        assert len(records) == 4
        assert all(r.class_key == "potato_late_blight" for r in records)

    def test_returns_none_when_there_is_no_images_component(self, tmp_path):
        assert pd._labels_dir_for(tmp_path / "flat" / "leaf.jpg") is None

    def test_tune_thresholds_label_for_agrees(self, dataset):
        img = dataset / "images" / "train" / "leaf0.jpg"
        resolved = tt.label_for(img)
        assert resolved == dataset / "labels" / "train" / "leaf0.txt"
        assert resolved.exists()

    def test_tune_thresholds_label_for_returns_none_rather_than_a_wrong_path(self, tmp_path):
        """Returning the image path with a .txt suffix made every image look
        like it had zero ground-truth boxes, biasing the sweep invisibly."""
        stray = tmp_path / "loose" / "leaf.jpg"
        stray.parent.mkdir(parents=True)
        assert tt.label_for(stray) is None


class TestPlantDocClassMapping:
    """PlantDoc ships 27 classes; we want 3. Mapping by hand-typed index
    (`--remap 0=1,1=0`) is the same silent failure mode as a mismatched
    data.yaml, so the mapping is derived from the source's own class names."""

    # The real PlantDoc class list, in its usual export order.
    PLANTDOC = [
        "Apple Scab Leaf", "Apple leaf", "Apple rust leaf", "Bell_pepper leaf",
        "Bell_pepper leaf spot", "Blueberry leaf", "Cherry leaf", "Corn Gray leaf spot",
        "Corn leaf blight", "Corn rust leaf", "Peach leaf", "Potato leaf",
        "Potato leaf early blight", "Potato leaf late blight", "Raspberry leaf",
        "Soyabean leaf", "Squash Powdery mildew leaf", "Strawberry leaf",
        "Tomato Early blight leaf", "Tomato Septoria leaf spot", "Tomato leaf",
        "Tomato leaf bacterial spot", "Tomato leaf late blight", "Tomato leaf mosaic virus",
        "Tomato leaf yellow virus", "Tomato mold leaf", "Tomato two spotted spider mites leaf",
    ]

    def test_derives_the_correct_indices_from_plantdoc(self):
        remap, mapped, dropped = pd.derive_remap(self.PLANTDOC)
        assert remap == {11: 2, 12: 0, 13: 1}
        assert len(mapped) == 3
        assert len(dropped) == 24

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Potato leaf early blight", "potato_early_blight"),
            ("Potato___Early_blight", "potato_early_blight"),
            ("potato_late_blight", "potato_late_blight"),
            ("Potato Leaf Late Blight", "potato_late_blight"),
            ("POTATO HEALTHY", "potato_healthy"),
            ("Potato leaf", "potato_healthy"),
        ],
    )
    def test_handles_the_naming_conventions_in_the_wild(self, name, expected):
        assert pd.map_source_class(name) == expected

    @pytest.mark.parametrize(
        "name",
        ["Tomato leaf late blight", "Corn leaf blight", "Apple rust leaf", "Bell_pepper leaf"],
    )
    def test_never_maps_another_crop_onto_a_potato_class(self, name):
        """'Tomato leaf late blight' contains 'late blight'. Matching on the
        disease alone would train tomato images as potato late blight."""
        assert pd.map_source_class(name) is None

    def test_refuses_to_guess_an_ambiguous_potato_label(self):
        """'Potato leaf blight' says neither early nor late. A guess here trains
        one disease's images under the other's label."""
        assert pd.map_source_class("Potato leaf blight") is None

    @pytest.mark.parametrize(
        "content,expected",
        [
            ("nc: 2\nnames: ['Potato leaf early blight', 'Potato leaf late blight']\n",
             ["Potato leaf early blight", "Potato leaf late blight"]),
            ("names:\n  0: Potato leaf early blight\n  1: Potato leaf late blight\n",
             ["Potato leaf early blight", "Potato leaf late blight"]),
            ("names:\n  - Potato leaf early blight\n  - Potato leaf late blight\n",
             ["Potato leaf early blight", "Potato leaf late blight"]),
        ],
        ids=["inline-list", "indexed-dict", "dash-list"],
    )
    def test_reads_every_data_yaml_names_form_roboflow_emits(self, tmp_path, content, expected):
        path = tmp_path / "data.yaml"
        path.write_text(content, encoding="utf-8")
        assert pd.read_yaml_names(path) == expected

    def test_indexed_form_keeps_the_first_entry(self, tmp_path):
        """Regression: a greedy \\s* swallowed the newline after `names:` and
        with it the first class, returning a list silently off by one."""
        path = tmp_path / "data.yaml"
        path.write_text(
            "names:\n  0: Potato leaf early blight\n  1: Potato leaf late blight\n",
            encoding="utf-8",
        )
        names = pd.read_yaml_names(path)
        assert len(names) == 2
        assert names[0] == "Potato leaf early blight"

    def test_finds_the_export_yaml(self, tmp_path):
        (tmp_path / "data.yaml").write_text("names: ['Potato leaf']\n", encoding="utf-8")
        assert pd.find_source_yaml(tmp_path) is not None
        assert pd.find_source_yaml(tmp_path / "nonexistent") is None


class TestStratifiedSplit:
    def _records(self, counts):
        out = []
        for class_key, n in counts.items():
            for i in range(n):
                out.append(
                    pd.Record(
                        src=pd.Path(f"/fake/{class_key}/img{i}.jpg"),
                        class_key=class_key,
                        source="pv",
                        label_lines=["0 0.5 0.5 0.9 0.9"],
                    )
                )
        return out

    def test_every_class_appears_in_every_split(self):
        records = self._records(
            {"potato_early_blight": 1000, "potato_late_blight": 1000, "potato_healthy": 152}
        )
        splits = pd.stratified_split(records, (0.8, 0.1, 0.1))
        for split in ("train", "val", "test"):
            present = {r.class_key for r in splits[split]}
            assert present == set(pd.CLASS_NAMES), f"{split} is missing a class"

    def test_minority_class_gets_a_measurable_val_split(self):
        """A flat 10% of 152 gives 15 val images, which is noise. The small-class
        rule lifts it to the minimum needed to actually measure the class."""
        records = self._records({"potato_healthy": 152})
        splits = pd.stratified_split(records, (0.8, 0.1, 0.1))
        val = [r for r in splits["val"] if r.class_key == "potato_healthy"]
        assert len(val) >= pd.MIN_VAL_PER_CLASS

    def test_no_image_leaks_between_splits(self):
        records = self._records({"potato_late_blight": 500})
        splits = pd.stratified_split(records, (0.8, 0.1, 0.1))
        seen = [r.src for s in ("train", "val", "test") for r in splits[s]]
        assert len(seen) == len(set(seen)) == 500

    def test_split_assignment_is_stable_across_runs(self):
        records = self._records({"potato_early_blight": 300})
        first = pd.stratified_split(records, (0.8, 0.1, 0.1))
        second = pd.stratified_split(list(reversed(records)), (0.8, 0.1, 0.1))
        assert {r.src for r in first["val"]} == {r.src for r in second["val"]}


class TestTrainBalancing:
    def _train(self, counts):
        out = []
        for class_key, n in counts.items():
            for i in range(n):
                out.append(
                    pd.Record(
                        src=pd.Path(f"/fake/{class_key}/img{i}.jpg"),
                        class_key=class_key,
                        source="pv",
                        label_lines=["0 0.5 0.5 0.9 0.9"],
                    )
                )
        return out

    def test_capping_and_oversampling_reach_parity(self):
        train = self._train(
            {"potato_early_blight": 800, "potato_late_blight": 800, "potato_healthy": 112}
        )
        balanced, info = pd.balance_train(train, cap=400, oversample_min=True)
        counts = {}
        for r in balanced:
            counts[r.class_key] = counts.get(r.class_key, 0) + 1
        assert set(counts.values()) == {400}
        assert info["duplicated"] == 288

    def test_reports_the_duplicate_burden_it_created(self):
        """72% of the healthy split being repeats is a real cost, and the run
        must say so rather than hiding it behind a parity claim."""
        train = self._train({"potato_late_blight": 400, "potato_healthy": 112})
        _, info = pd.balance_train(train, cap=400, oversample_min=True)
        share = (info["after"]["potato_healthy"] - info["before"]["potato_healthy"]) / info[
            "after"
        ]["potato_healthy"]
        assert share > pd.MAX_DUPLICATE_SHARE

    def test_capping_alone_creates_no_duplicates(self):
        train = self._train({"potato_early_blight": 800, "potato_late_blight": 800})
        _, info = pd.balance_train(train, cap=400, oversample_min=False)
        assert info["duplicated"] == 0
