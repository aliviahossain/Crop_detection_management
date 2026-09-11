"""Shared helpers for the croprow_disease (crop-row plant health) notebooks.

Scope: two classes -- ``healthy`` (green, vigorous canopy) and ``unhealthy``
(brown / yellowed / otherwise off-colour). Detection boxes only. This module
deliberately does NOT import anything from the potato disease-detection code
(``ml/``) nor from the single-class ``croprow/`` module; it is a parallel stack
with the same shape, so the two can be trained and served independently.

Dataset: LettuceMOTS (the same frames ``croprow/`` uses). Its ground truth is
YOLOv5 *segmentation polygons* with a single class, so this module does two
derivations per instance, both deterministic and both from real data:

* **box** -- axis-aligned min/max of the polygon's normalized vertices
  (identical to croprow's derivation);
* **class** -- a colour rule over the real pixels the polygon encloses, see
  ``health.py``. Green canopy -> ``healthy``; brown/off canopy -> ``unhealthy``.

The class half is an **auto-label, not verified disease ground truth** -- say so
wherever its metrics are reported. If a dataset ever ships real 2-class boxes,
``inspect_label_format`` detects that and the labels pass through unchanged.

On-disk layout the helpers assume (paths are relative to LETTUCE_ROOT)::

    train/images/<seq>/<frame>.png       # video frames, per sequence folder
    LettuceMOTSyolo/<seq>/<frame>.txt    # polygon labels, TRAIN sequences only
    test/images/<seq>/<frame>.png        # frames with NO yolo labels

Converted 2-class box labels are written to a SEPARATE mirror tree so they can
never collide with the single-class labels croprow writes into ``train/labels``::

    train/labels_health/<seq>/<frame>.txt    # "<0|1> cx cy w h" (normalized)
"""

from __future__ import annotations

import os
import random
import shutil
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np
import yaml

from .health import (  # re-exported so notebooks import one module
    CLASS_COLORS,
    CLASS_NAMES,
    DEFAULT_PARAMS,
    HEALTHY,
    UNHEALTHY,
    HealthParams,
    bbox_from_polygon,
    classify_bbox,
    classify_polygon,
    judgeable,
)

inf = float("inf")

NUM_CLASSES = len(CLASS_NAMES)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")

# Label subdir name. Deliberately NOT "labels" -- croprow writes single-class
# labels there for the same frames, and Ultralytics picks the tree by swapping
# "images" -> "labels" in the image path, so sharing the name would mean
# whichever module ran last silently decides what the other one trains on.
LABEL_SUBDIR = "labels_health"


# --------------------------------------------------------------------------- #
# Paths / config
# --------------------------------------------------------------------------- #
def resolve_lettuce_root(override: str | os.PathLike | None = None) -> Path:
    """Resolve the LettuceMOTS root.

    Precedence: explicit ``override`` (a notebook config cell) > ``LETTUCE_ROOT``
    env var. No absolute path is baked into this module -- the caller supplies
    it. Raises with a clear message if nothing resolves or the folder is missing
    the expected structure.
    """
    raw = override if override else os.environ.get("LETTUCE_ROOT")
    if not raw:
        raise RuntimeError(
            "LettuceMOTS root not set. Set the LETTUCE_ROOT env var or pass the "
            "path from the notebook config cell (never hardcode it in code)."
        )
    root = Path(raw).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"LETTUCE_ROOT does not exist or is not a dir: {root}")
    missing = [p for p in ("train/images", "LettuceMOTSyolo") if not (root / p).is_dir()]
    if missing:
        raise FileNotFoundError(
            f"{root} is missing expected subdir(s): {missing}. "
            "Assumption failed -- stop and check the dataset path/layout."
        )
    return root


def train_images_dir(root: Path) -> Path:
    return root / "train" / "images"


def poly_labels_dir(root: Path) -> Path:
    return root / "LettuceMOTSyolo"


def box_labels_dir(root: Path) -> Path:
    """Where converted 2-class YOLO box labels are written."""
    return root / "train" / LABEL_SUBDIR


def test_images_dir(root: Path) -> Path:
    return root / "test" / "images"


# --------------------------------------------------------------------------- #
# Sequences / frames
# --------------------------------------------------------------------------- #
def labeled_sequences(root: Path) -> list[str]:
    """Sequence folders that have BOTH frames and polygon labels (train set)."""
    imgs = {p.name for p in train_images_dir(root).iterdir() if p.is_dir()}
    labs = {p.name for p in poly_labels_dir(root).iterdir() if p.is_dir()}
    return sorted(imgs & labs)


def test_sequences(root: Path) -> list[str]:
    d = test_images_dir(root)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir())


def _list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def frame_pairs(root: Path, seq: str) -> list[tuple[Path, Path]]:
    """(image_path, polygon_label_path) pairs for one train sequence.

    Only frames that have a matching label file are returned.
    """
    img_folder = train_images_dir(root) / seq
    lab_folder = poly_labels_dir(root) / seq
    pairs: list[tuple[Path, Path]] = []
    for img in _list_images(img_folder):
        lab = lab_folder / (img.stem + ".txt")
        if lab.is_file():
            pairs.append((img, lab))
    return pairs


def image_paths_for_seqs(root: Path, seqs: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for seq in seqs:
        out.extend(img for img, _ in frame_pairs(root, seq))
    return out


# --------------------------------------------------------------------------- #
# Label format inspection
# --------------------------------------------------------------------------- #
def _read_label_lines(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append([float(t) for t in line.split()])
    return rows


def inspect_label_format(root: Path, max_files: int | None = None) -> dict:
    """Scan label files and classify the format.

    A YOLOv5 *detection box* line is exactly 5 tokens: ``class cx cy w h``.
    A *segmentation polygon* line is ``class x1 y1 ... xn yn`` -> an odd token
    count > 5. Also reports the distinct class ids present, so a notebook can
    tell apart the two real cases:

    * single-class polygons (LettuceMOTS)  -> derive boxes AND colour classes;
    * 2-class boxes already labelled health -> pass through unchanged.
    """
    files: list[Path] = []
    for seq in labeled_sequences(root):
        files.extend(sorted((poly_labels_dir(root) / seq).glob("*.txt")))
    if max_files is not None:
        files = files[:max_files]

    box_lines = poly_lines = other_lines = 0
    class_ids: set[int] = set()
    min_tok = None
    max_tok = 0
    for f in files:
        for row in _read_label_lines(f):
            n = len(row)
            max_tok = max(max_tok, n)
            min_tok = n if min_tok is None else min(min_tok, n)
            class_ids.add(int(row[0]))
            if n == 5:
                box_lines += 1
            elif n > 5 and n % 2 == 1:
                poly_lines += 1
            else:
                other_lines += 1

    total = box_lines + poly_lines + other_lines
    is_boxes = total > 0 and box_lines == total
    return {
        "files_scanned": len(files),
        "total_lines": total,
        "box_lines": box_lines,
        "polygon_lines": poly_lines,
        "other_lines": other_lines,
        "class_ids": sorted(class_ids),
        "min_tokens": min_tok or 0,
        "max_tokens": max_tok,
        "is_boxes": is_boxes,
        "is_polygons": total > 0 and poly_lines > 0 and box_lines == 0,
        # Real 2-class ground truth -> nothing to derive, pass straight through.
        "is_two_class_boxes": is_boxes and class_ids == {HEALTHY, UNHEALTHY},
    }


# --------------------------------------------------------------------------- #
# Polygon + pixels -> (class, box)
# --------------------------------------------------------------------------- #
def imread_bgr(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"cv2 could not read image: {path}")
    return bgr


def imread_rgb(path: Path) -> np.ndarray:
    """Read an image as RGB (for matplotlib inline display)."""
    return cv2.cvtColor(imread_bgr(path), cv2.COLOR_BGR2RGB)


def instances_for_frame(
    img_bgr: np.ndarray,
    label_path: Path,
    params: HealthParams = DEFAULT_PARAMS,
    trust_label_class: bool = False,
) -> list[dict]:
    """Every annotated instance in one frame, with its derived class and box.

    Returns dicts ``{cls, cx, cy, w, h, score, canopy_px, sharpness,
    mean_value, judged, source}`` where
    ``score`` is the continuous health score (see ``health.py``) and ``source``
    records whether the class was derived from a polygon, derived from a box, or
    read straight from a real 2-class label. Degenerate (zero-area) annotations
    are dropped.

    ``trust_label_class`` must be set by the caller from
    ``inspect_label_format(...)["is_two_class_boxes"]``. It is a whole-dataset
    fact, not a per-line one: in a real 2-class file a ``0`` means a human
    called that plant healthy and must be kept, while in a single-class file the
    same ``0`` only means "lettuce" and the class still has to be derived. The
    two cases are indistinguishable from one line, so the decision is passed in.
    """
    out: list[dict] = []
    for row in _read_label_lines(label_path):
        n = len(row)
        if n == 5:
            cls_in, cx, cy, w, h = int(row[0]), row[1], row[2], row[3], row[4]
            if w <= 0 or h <= 0:
                continue
            if trust_label_class:
                cls, score, canopy, sharp, val = cls_in, float("nan"), -1, inf, inf
                src = "label"
            else:
                cls, score, canopy, sharp, val = classify_bbox(
                    img_bgr, (cx, cy, w, h), params)
                src = "bbox"
        elif n > 5 and n % 2 == 1:
            box = bbox_from_polygon(row[1:])
            if box is None:
                continue
            cx, cy, w, h = box
            cls, score, canopy, sharp, val = classify_polygon(img_bgr, row[1:], params)
            src = "polygon"
        else:
            continue
        out.append({
            "cls": int(cls),
            "cx": min(max(float(cx), 0.0), 1.0),
            "cy": min(max(float(cy), 0.0), 1.0),
            "w": min(max(float(w), 0.0), 1.0),
            "h": min(max(float(h), 0.0), 1.0),
            "score": float(score),
            "canopy_px": int(canopy),
            "sharpness": float(sharp),
            "mean_value": float(val),
            # False -> the class was defaulted by the quality gate, not decided
            # on colour. Counted separately everywhere it is reported.
            "judged": bool(src == "label" or judgeable(canopy, sharp, val, params)),
            "source": src,
        })
    return out


def instances_for_image(
    root: Path,
    img_path: Path,
    params: HealthParams = DEFAULT_PARAMS,
    trust_label_class: bool = False,
) -> list[dict]:
    """Instances for a train frame, derived on the fly from its polygon label.

    Lets ``02_verify_labels`` visualise straight from the source annotations
    without depending on the conversion step in 01 having run.
    """
    img_path = Path(img_path)
    lab = poly_labels_dir(root) / img_path.parent.name / (img_path.stem + ".txt")
    if not lab.is_file():
        return []
    return instances_for_frame(imread_bgr(img_path), lab, params, trust_label_class)


# --------------------------------------------------------------------------- #
# Conversion (write 2-class YOLO box labels)
# --------------------------------------------------------------------------- #
def _format_label_lines(instances: Iterable[dict]) -> str:
    return "".join(
        f"{i['cls']} {i['cx']:.6f} {i['cy']:.6f} {i['w']:.6f} {i['h']:.6f}\n"
        for i in instances
    )


def convert_sequence(
    root: Path,
    seq: str,
    params: HealthParams = DEFAULT_PARAMS,
    trust_label_class: bool = False,
) -> dict:
    """Write 2-class box labels for one sequence; return per-class counts.

    Each frame is read once (the colour rule needs the pixels), so this is I/O
    bound and takes a few seconds per sequence -- not instant like croprow's
    geometry-only conversion.
    """
    out_dir = box_labels_dir(root) / seq
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {"healthy": 0, "unhealthy": 0, "frames": 0, "low_confidence": 0}
    for img, lab in frame_pairs(root, seq):
        inst = instances_for_frame(imread_bgr(img), lab, params, trust_label_class)
        (out_dir / (lab.stem + ".txt")).write_text(_format_label_lines(inst))
        counts["frames"] += 1
        for i in inst:
            counts["healthy" if i["cls"] == HEALTHY else "unhealthy"] += 1
            if not i["judged"]:
                counts["low_confidence"] += 1
    return counts


def convert_all(
    root: Path,
    seqs: Iterable[str],
    params: HealthParams = DEFAULT_PARAMS,
    trust_label_class: bool = False,
    progress: bool = True,
) -> dict[str, dict]:
    """Convert every given sequence; return ``{seq: counts}``."""
    out: dict[str, dict] = {}
    for seq in seqs:
        counts = convert_sequence(root, seq, params, trust_label_class)
        out[seq] = counts
        if progress:
            print(f"  seq {seq}: {counts['frames']:4d} frames | "
                  f"healthy {counts['healthy']:6d} | "
                  f"unhealthy {counts['unhealthy']:6d} | "
                  f"low-conf {counts['low_confidence']:5d}", flush=True)
    return out


def label_report(
    root: Path,
    seqs: Iterable[str],
    params: HealthParams = DEFAULT_PARAMS,
    sample_frames: int | None = None,
    seed: int = 42,
) -> dict:
    """Score distribution + class balance over the derived labels.

    Reads the *source* polygons (not the converted files), so it can be run
    before conversion to tune ``green_frac_threshold`` against what the crop
    actually looks like. ``sample_frames`` limits the scan -- scoring every
    frame means decoding every PNG, which is slow on the full set.

    Returns counts, the score histogram edges/values, and the share of
    instances whose score fell too close to the threshold to be decided
    confidently -- the number to quote when someone asks how good these
    auto-labels are.
    """
    frames: list[tuple[Path, Path]] = []
    for seq in seqs:
        frames.extend(frame_pairs(root, seq))
    if sample_frames is not None and sample_frames < len(frames):
        frames = random.Random(seed).sample(frames, sample_frames)

    scores: list[float] = []
    n_healthy = n_unhealthy = n_low_conf = 0
    for img, lab in frames:
        for i in instances_for_frame(imread_bgr(img), lab, params):
            if i["cls"] == HEALTHY:
                n_healthy += 1
            else:
                n_unhealthy += 1
            if not i["judged"]:
                n_low_conf += 1
            elif not np.isnan(i["score"]):
                scores.append(i["score"])

    arr = np.asarray(scores, dtype=np.float64)
    total = n_healthy + n_unhealthy
    # "Borderline" = within 0.05 of the cut. A big number here means the
    # threshold is sitting inside the bulk of the distribution and the split is
    # arbitrary; a small one means the two populations are genuinely separated.
    margin = 0.05
    borderline = int(np.count_nonzero(
        np.abs(arr - params.green_frac_threshold) < margin
    )) if arr.size else 0
    hist, edges = (np.histogram(arr, bins=20, range=(0.0, 1.0))
                   if arr.size else (np.zeros(20, int), np.linspace(0, 1, 21)))
    return {
        "frames_scanned": len(frames),
        "instances": total,
        "healthy": n_healthy,
        "unhealthy": n_unhealthy,
        "healthy_pct": (100.0 * n_healthy / total) if total else 0.0,
        "unhealthy_pct": (100.0 * n_unhealthy / total) if total else 0.0,
        "low_confidence": n_low_conf,
        "borderline": borderline,
        "borderline_pct": (100.0 * borderline / arr.size) if arr.size else 0.0,
        "borderline_margin": margin,
        "score_mean": float(arr.mean()) if arr.size else 0.0,
        "score_median": float(np.median(arr)) if arr.size else 0.0,
        "score_p05": float(np.percentile(arr, 5)) if arr.size else 0.0,
        "score_p95": float(np.percentile(arr, 95)) if arr.size else 0.0,
        "hist": hist.tolist(),
        "bin_edges": edges.tolist(),
        "params": params.as_dict(),
    }


def count_instances_for_seqs(
    root: Path, seqs: Iterable[str], params: HealthParams = DEFAULT_PARAMS
) -> dict[str, int]:
    """Per-class instance counts read back from the CONVERTED label files.

    Cheap (no image decoding) but requires ``convert_all`` to have run.
    """
    counts = {"healthy": 0, "unhealthy": 0}
    for seq in seqs:
        for _img, lab in frame_pairs(root, seq):
            dst = box_labels_dir(root) / seq / (lab.stem + ".txt")
            if not dst.is_file():
                continue
            for row in _read_label_lines(dst):
                counts["healthy" if int(row[0]) == HEALTHY else "unhealthy"] += 1
    return counts


# --------------------------------------------------------------------------- #
# Split (BY SEQUENCE FOLDER -- never by random frame)
# --------------------------------------------------------------------------- #
def split_sequences(
    seqs: Sequence[str], val_frac: float = 0.25, seed: int = 42
) -> tuple[list[str], list[str]]:
    """Split sequence *folders* into (train, val).

    Frames inside one sequence are consecutive video frames, so a whole sequence
    must land entirely in train or entirely in val -- otherwise near-identical
    adjacent frames leak across the split and validation is meaningless. At
    least one sequence is guaranteed to each side.

    Same seed and fraction as croprow, so the two modules split the same
    sequences the same way and their numbers stay comparable.
    """
    seqs = list(seqs)
    if len(seqs) < 2:
        raise ValueError(f"Need >=2 sequences to split, got {len(seqs)}: {seqs}")
    rng = random.Random(seed)
    shuffled = seqs[:]
    rng.shuffle(shuffled)
    n_val = max(1, round(len(shuffled) * val_frac))
    n_val = min(n_val, len(shuffled) - 1)  # keep at least one for train
    val = sorted(shuffled[:n_val])
    train = sorted(shuffled[n_val:])
    return train, val


def write_list_file(path: Path, image_paths: Iterable[Path]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    paths = [str(Path(p).resolve()) for p in image_paths]
    path.write_text("\n".join(paths) + ("\n" if paths else ""))
    return len(paths)


def make_data_yaml(
    out_path: Path,
    train_txt: Path,
    val_txt: Path,
    nc: int = NUM_CLASSES,
    names: Sequence[str] = CLASS_NAMES,
) -> Path:
    """Emit an Ultralytics data yaml (nc=2). Uses absolute .txt list paths."""
    out_path = Path(out_path)
    data = {
        "train": str(Path(train_txt).resolve()),
        "val": str(Path(val_txt).resolve()),
        "nc": int(nc),
        "names": list(names),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    return out_path


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def draw_instances(
    img: np.ndarray,
    instances: Iterable[dict],
    thickness: int = 2,
    show_score: bool = True,
    rgb: bool = False,
) -> np.ndarray:
    """Draw class-coloured boxes on a copy of the image.

    Green box = healthy, orange-red = unhealthy. ``rgb=True`` swaps the colour
    channels so the result is right for matplotlib (which wants RGB) instead of
    cv2 windows/writers (which want BGR).
    """
    out = img.copy()
    h, w = out.shape[:2]
    for inst in instances:
        cls = int(inst["cls"])
        color = CLASS_COLORS.get(cls, (200, 200, 200))
        if rgb:
            color = (color[2], color[1], color[0])
        x0 = int(round((inst["cx"] - inst["w"] / 2) * w))
        y0 = int(round((inst["cy"] - inst["h"] / 2) * h))
        x1 = int(round((inst["cx"] + inst["w"] / 2) * w))
        y1 = int(round((inst["cy"] + inst["h"] / 2) * h))
        cv2.rectangle(out, (x0, y0), (x1, y1), color, thickness)
        label = CLASS_NAMES[cls]
        score = inst.get("score", float("nan"))
        if show_score and score == score:      # NaN check without importing math
            label += f" {score:.2f}"
        cv2.putText(out, label, (x0, max(10, y0 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
    return out


# --------------------------------------------------------------------------- #
# Portable dataset bundle
# --------------------------------------------------------------------------- #
def package_dataset(
    root: Path,
    out_dir: Path,
    train_seqs: Sequence[str],
    val_seqs: Sequence[str],
    params: HealthParams = DEFAULT_PARAMS,
    copy_images: bool = True,
    trust_label_class: bool = False,
) -> dict:
    """Build a portable, drop-in 2-class YOLO dataset under ``out_dir``.

    Layout (standard Ultralytics, labels mirror images)::

        <out_dir>/images/train/<seq>/<frame>.png
        <out_dir>/labels/train/<seq>/<frame>.txt   # "<0|1> cx cy w h"
        <out_dir>/data.yaml                        # nc=2

    Note the bundle uses the plain ``labels/`` name: inside its own folder there
    is no single-class tree to collide with, and Ultralytics expects that name.
    Classes are re-derived here from the polygons + pixels, so the bundle is
    self-contained and does not depend on 01 having run. The written
    ``data.yaml`` uses an absolute ``path`` (correct on this machine); ship
    ``set_yaml_path.py`` alongside so the trainer repoints it after unzip.
    Returns a manifest dict.
    """
    root = Path(root)
    out = Path(out_dir)
    manifest: dict = {
        "out_dir": str(out.resolve()),
        "splits": {},
        "health_params": params.as_dict(),
        "label_source": "real 2-class labels" if trust_label_class
                        else "colour-derived from LettuceMOTS polygons",
    }

    for split, seqs in (("train", list(train_seqs)), ("val", list(val_seqs))):
        n_img = n_healthy = n_unhealthy = 0
        for seq in seqs:
            img_out = out / "images" / split / seq
            lab_out = out / "labels" / split / seq
            img_out.mkdir(parents=True, exist_ok=True)
            lab_out.mkdir(parents=True, exist_ok=True)
            for img, lab in frame_pairs(root, seq):
                bgr = imread_bgr(img)
                inst = instances_for_frame(bgr, lab, params, trust_label_class)
                if copy_images:
                    shutil.copy2(img, img_out / img.name)
                (lab_out / (img.stem + ".txt")).write_text(_format_label_lines(inst))
                n_img += 1
                n_healthy += sum(1 for i in inst if i["cls"] == HEALTHY)
                n_unhealthy += sum(1 for i in inst if i["cls"] == UNHEALTHY)
        manifest["splits"][split] = {
            "sequences": seqs, "images": n_img,
            "healthy": n_healthy, "unhealthy": n_unhealthy,
            "boxes": n_healthy + n_unhealthy,
        }

    yaml_path = out / "data.yaml"
    data = {
        "path": str(out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "nc": NUM_CLASSES,
        "names": list(CLASS_NAMES),
    }
    with yaml_path.open("w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    manifest["data_yaml"] = str(yaml_path.resolve())
    return manifest


# --------------------------------------------------------------------------- #
# RESULTS.md logging
# --------------------------------------------------------------------------- #
RESULTS_COLUMNS = [
    "run", "dataset", "labels", "mAP50", "mAP50-95", "precision", "recall",
    "mAP50 healthy", "mAP50 unhealthy", "epochs", "imgsz",
]
_RESULTS_HEADER = (
    "| " + " | ".join(RESULTS_COLUMNS) + " |\n"
    "| " + " | ".join("---" for _ in RESULTS_COLUMNS) + " |\n"
)
_RESULTS_PREAMBLE = (
    "# croprow_disease RESULTS\n\n"
    "One row per run. Public (LettuceMOTS) and own-frame metrics are kept as\n"
    "separate rows -- never merged. The `labels` column records where the\n"
    "healthy/unhealthy classes came from: `colour-derived` means the auto-label\n"
    "rule in `health.py`, `annotated` means real human health labels. A number\n"
    "against colour-derived labels measures agreement with that rule, NOT\n"
    "verified disease accuracy -- do not quote it as the latter.\n\n"
    "Per-class mAP50 is reported alongside the mean because the two classes are\n"
    "imbalanced; a strong overall mAP can hide a weak `unhealthy` class, which\n"
    "is the one that actually matters operationally.\n\n"
)


def append_results_row(
    results_md: Path,
    run: str,
    dataset: str,
    map50: float,
    map5095: float,
    precision: float,
    recall: float,
    epochs: int | str,
    imgsz: int | str,
    map50_healthy: float | str = "-",
    map50_unhealthy: float | str = "-",
    labels: str = "colour-derived",
) -> None:
    """Append one run's metrics as a table row to RESULTS.md.

    ``dataset`` MUST identify the eval set (e.g. 'LettuceMOTS-val' or
    'own-frames'). Public and own-data metrics are logged as SEPARATE rows --
    never a single merged accuracy.
    """
    results_md = Path(results_md)

    def fmt(v):
        return f"{v:.4f}" if isinstance(v, (int, float)) else str(v)

    row = (
        f"| {run} | {dataset} | {labels} | {map50:.4f} | {map5095:.4f} | "
        f"{precision:.4f} | {recall:.4f} | {fmt(map50_healthy)} | "
        f"{fmt(map50_unhealthy)} | {epochs} | {imgsz} |\n"
    )
    if not results_md.is_file() or _RESULTS_HEADER not in results_md.read_text():
        existing = results_md.read_text() if results_md.is_file() else ""
        results_md.write_text(
            (existing + "\n" if existing else "")
            + _RESULTS_PREAMBLE + _RESULTS_HEADER + row
        )
    else:
        with results_md.open("a") as fh:
            fh.write(row)


# --------------------------------------------------------------------------- #
# Class-balance gate
# --------------------------------------------------------------------------- #
MIN_USABLE_CLASS_PCT = 5.0


def check_class_balance(
    counts: dict[str, int], min_pct: float = MIN_USABLE_CLASS_PCT
) -> dict:
    """Judge whether a 2-class split is actually trainable.

    A detector needs a real population of BOTH classes. LettuceMOTS is a
    uniformly healthy crop -- once blurred and shadowed captures are excluded by
    the quality gate it yields **zero** unhealthy instances -- so the honest
    outcome for that dataset is "this cannot train a two-class model", not a
    yaml that trains a model whose ``unhealthy`` head has never seen a positive.

    Returns a verdict dict. ``ok`` is False when either class is below
    ``min_pct`` of instances; callers should surface ``message`` loudly rather
    than proceeding quietly.
    """
    healthy = int(counts.get("healthy", 0))
    unhealthy = int(counts.get("unhealthy", 0))
    total = healthy + unhealthy
    if total == 0:
        return {"ok": False, "total": 0, "healthy": 0, "unhealthy": 0,
                "healthy_pct": 0.0, "unhealthy_pct": 0.0,
                "message": "No instances at all -- check the dataset path and "
                           "that conversion actually ran."}

    h_pct = 100.0 * healthy / total
    u_pct = 100.0 * unhealthy / total
    starved = [n for n, p in (("healthy", h_pct), ("unhealthy", u_pct)) if p < min_pct]
    if not starved:
        msg = (f"Class balance OK: healthy {healthy} ({h_pct:.1f}%), "
               f"unhealthy {unhealthy} ({u_pct:.1f}%).")
    else:
        msg = (
            f"UNUSABLE FOR 2-CLASS TRAINING: {' and '.join(starved)} is below "
            f"{min_pct:.0f}% of {total} instances "
            f"(healthy {healthy} = {h_pct:.1f}%, unhealthy {unhealthy} = {u_pct:.1f}%).\n"
            "\n"
            "This is a property of the DATA, not a bug in the pipeline. The\n"
            "colour rule works -- there simply are not enough plants of one\n"
            "class in these frames to learn from. Training anyway produces a\n"
            "model that predicts the majority class for everything and reports\n"
            "a high mAP while being useless in the field.\n"
            "\n"
            "To get a trainable set, use frames that actually contain the\n"
            "missing class:\n"
            "  - a provided healthy/unhealthy dataset -> notebook 01b, which\n"
            "    repoints data/health.yaml at it; 03-08 then work unchanged; or\n"
            "  - your own cultivator-camera captures of affected plants,\n"
            "    labelled healthy/unhealthy -> notebook 04 (set OWN_DATA_YAML)\n"
            "    to fine-tune these weights on them."
        )
    return {
        "ok": not starved,
        "total": total,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "healthy_pct": h_pct,
        "unhealthy_pct": u_pct,
        "starved": starved,
        "message": msg,
    }
