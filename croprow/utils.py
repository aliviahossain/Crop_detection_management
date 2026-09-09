"""Shared helpers for the croprow (crop-row localization) notebooks.

Scope: single class (lettuce). Detection boxes only. This module deliberately
does NOT import anything from the potato disease-detection code (ml/).

Dataset: LettuceMOTS. Its ground-truth labels are YOLOv5 *segmentation
polygons* (verified in 01_dataset_prep -- see ``inspect_label_format``), not
detection boxes, so we derive an axis-aligned bounding box from each polygon's
min/max normalized coordinates. That derivation is deterministic and comes
straight from the real annotations -- nothing synthetic or generated.

On-disk layout the helpers assume (paths are relative to LETTUCE_ROOT)::

    train/images/<seq>/<frame>.png      # video frames, per sequence folder
    train/instances/<seq>/<frame>.png   # MOTS instance masks (unused here)
    test/images/<seq>/<frame>.png       # frames with NO yolo labels
    LettuceMOTSyolo/<seq>/<frame>.txt   # polygon labels, TRAIN sequences only

Converted box labels are written next to the images in the YOLO-standard
mirror location so Ultralytics can find them automatically::

    train/labels/<seq>/<frame>.txt      # "0 cx cy w h" (normalized)
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

# Single class only. Do not add weed/disease classes.
CLASS_ID = 0
CLASS_NAMES = ["lettuce"]

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


# --------------------------------------------------------------------------- #
# Paths / config
# --------------------------------------------------------------------------- #
def resolve_lettuce_root(override: str | os.PathLike | None = None) -> Path:
    """Resolve the LettuceMOTS root.

    Precedence: explicit ``override`` (a notebook config cell) > ``LETTUCE_ROOT``
    env var. No absolute path is baked into this module -- the caller supplies
    it. Raises with a clear message if nothing resolves or the folder is
    missing the expected structure.
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
    """Where converted YOLO box labels are written (mirrors train/images)."""
    return root / "train" / "labels"


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
# Label format inspection + polygon -> box conversion
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
    A YOLOv5 *segmentation polygon* line is ``class x1 y1 ... xn yn`` -> an odd
    number of tokens > 5. Returns counts so a notebook can assert/branch and,
    if it turns out to be boxes after all, skip conversion.
    """
    files: list[Path] = []
    for seq in labeled_sequences(root):
        files.extend(sorted((poly_labels_dir(root) / seq).glob("*.txt")))
    if max_files is not None:
        files = files[:max_files]

    box_lines = poly_lines = other_lines = 0
    min_tok = None
    max_tok = 0
    for f in files:
        for row in _read_label_lines(f):
            n = len(row)
            max_tok = max(max_tok, n)
            min_tok = n if min_tok is None else min(min_tok, n)
            if n == 5:
                box_lines += 1
            elif n > 5 and n % 2 == 1:
                poly_lines += 1
            else:
                other_lines += 1

    total = box_lines + poly_lines + other_lines
    return {
        "files_scanned": len(files),
        "total_lines": total,
        "box_lines": box_lines,
        "polygon_lines": poly_lines,
        "other_lines": other_lines,
        "min_tokens": min_tok or 0,
        "max_tokens": max_tok,
        "is_boxes": total > 0 and box_lines == total,
        "is_polygons": total > 0 and poly_lines > 0 and box_lines == 0,
    }


def line_to_bbox(tokens: Sequence[float]) -> tuple[int, float, float, float, float] | None:
    """Convert one label line to a normalized YOLO box ``(cls, cx, cy, w, h)``.

    - 5 tokens -> already a box; passed through (class forced to CLASS_ID).
    - polygon  -> axis-aligned bbox from min/max of the (x, y) vertices.

    Coords are clamped to [0, 1]. Returns ``None`` for a degenerate (zero-area)
    box so callers can skip it.
    """
    n = len(tokens)
    if n == 5:
        _, cx, cy, w, h = tokens
    elif n > 5 and n % 2 == 1:
        xs = np.asarray(tokens[1::2], dtype=np.float64)
        ys = np.asarray(tokens[2::2], dtype=np.float64)
        x0, x1 = float(xs.min()), float(xs.max())
        y0, y1 = float(ys.min()), float(ys.max())
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        w, h = x1 - x0, y1 - y0
    else:
        return None

    cx = min(max(cx, 0.0), 1.0)
    cy = min(max(cy, 0.0), 1.0)
    w = min(max(w, 0.0), 1.0)
    h = min(max(h, 0.0), 1.0)
    if w <= 0.0 or h <= 0.0:
        return None
    return CLASS_ID, cx, cy, w, h


def boxes_for_label_file(path: Path) -> list[tuple[float, float, float, float]]:
    """All normalized boxes (cx, cy, w, h) derived from a polygon/box label."""
    out: list[tuple[float, float, float, float]] = []
    for row in _read_label_lines(path):
        box = line_to_bbox(row)
        if box is not None:
            out.append(box[1:])
    return out


def boxes_for_image(root: Path, img_path: Path) -> list[tuple[float, float, float, float]]:
    """Boxes for a train frame, derived on the fly from its polygon label.

    Lets 02_verify_labels visualize straight from the source annotations
    without depending on the conversion step having run.
    """
    img_path = Path(img_path)
    seq = img_path.parent.name
    lab = poly_labels_dir(root) / seq / (img_path.stem + ".txt")
    if not lab.is_file():
        return []
    return boxes_for_label_file(lab)


def convert_sequence(root: Path, seq: str) -> int:
    """Write converted box labels for one sequence; return the box count."""
    out_dir = box_labels_dir(root) / seq
    out_dir.mkdir(parents=True, exist_ok=True)
    n_boxes = 0
    for _img, lab in frame_pairs(root, seq):
        boxes = []
        for row in _read_label_lines(lab):
            b = line_to_bbox(row)
            if b is not None:
                boxes.append(b)
        dst = out_dir / (lab.stem + ".txt")
        dst.write_text(
            "".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in boxes)
        )
        n_boxes += len(boxes)
    return n_boxes


def convert_all(root: Path, seqs: Iterable[str]) -> dict[str, int]:
    """Convert every given sequence; return {seq: box_count}."""
    return {seq: convert_sequence(root, seq) for seq in seqs}


def count_boxes_for_seqs(root: Path, seqs: Iterable[str]) -> int:
    total = 0
    for seq in seqs:
        for _img, lab in frame_pairs(root, seq):
            total += len(boxes_for_label_file(lab))
    return total


# --------------------------------------------------------------------------- #
# Split (BY SEQUENCE FOLDER -- never by random frame)
# --------------------------------------------------------------------------- #
def split_sequences(
    seqs: Sequence[str], val_frac: float = 0.25, seed: int = 42
) -> tuple[list[str], list[str]]:
    """Split sequence *folders* into (train, val).

    Frames inside one sequence are consecutive video frames, so a whole
    sequence must land entirely in train or entirely in val -- otherwise
    near-identical adjacent frames leak across the split and validation is
    meaningless. At least one sequence is guaranteed to each side.
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
    nc: int = 1,
    names: Sequence[str] = CLASS_NAMES,
) -> Path:
    """Emit an Ultralytics data yaml (nc=1). Uses absolute .txt list paths."""
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
def draw_boxes(
    img_bgr: np.ndarray,
    boxes_norm: Iterable[tuple[float, float, float, float]],
    color: tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2,
) -> np.ndarray:
    """Draw normalized (cx, cy, w, h) boxes on a copy of the image."""
    out = img_bgr.copy()
    h, w = out.shape[:2]
    for cx, cy, bw, bh in boxes_norm:
        x0 = int(round((cx - bw / 2) * w))
        y0 = int(round((cy - bh / 2) * h))
        x1 = int(round((cx + bw / 2) * w))
        y1 = int(round((cy + bh / 2) * h))
        cv2.rectangle(out, (x0, y0), (x1, y1), color, thickness)
    return out


def imread_rgb(path: Path) -> np.ndarray:
    """Read an image as RGB (for matplotlib inline display)."""
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"cv2 could not read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


# --------------------------------------------------------------------------- #
# RESULTS.md logging
# --------------------------------------------------------------------------- #
RESULTS_COLUMNS = [
    "run", "dataset", "mAP50", "mAP50-95", "precision", "recall", "epochs", "imgsz",
]
_RESULTS_HEADER = (
    "| " + " | ".join(RESULTS_COLUMNS) + " |\n"
    "| " + " | ".join("---" for _ in RESULTS_COLUMNS) + " |\n"
)


def package_dataset(
    root: Path,
    out_dir: Path,
    train_seqs: Sequence[str],
    val_seqs: Sequence[str],
    copy_images: bool = True,
) -> dict:
    """Build a portable, drop-in YOLO detection dataset under ``out_dir``.

    Layout (standard Ultralytics, labels mirror images)::

        <out_dir>/images/train/<seq>/<frame>.png
        <out_dir>/images/val/<seq>/<frame>.png
        <out_dir>/labels/train/<seq>/<frame>.txt   # "0 cx cy w h"
        <out_dir>/labels/val/<seq>/<frame>.txt
        <out_dir>/data.yaml

    Box labels are derived from the LettuceMOTS polygons here, so the bundle is
    self-contained and does not depend on the converted labels from 01. The
    written ``data.yaml`` uses an absolute ``path`` (correct on this machine);
    ship ``set_yaml_path.py`` alongside so the trainer repoints it after unzip.
    Returns a manifest dict.
    """
    root = Path(root)
    out = Path(out_dir)
    manifest: dict = {"out_dir": str(out.resolve()), "splits": {}}

    for split, seqs in (("train", list(train_seqs)), ("val", list(val_seqs))):
        n_img = n_box = 0
        for seq in seqs:
            img_out = out / "images" / split / seq
            lab_out = out / "labels" / split / seq
            img_out.mkdir(parents=True, exist_ok=True)
            lab_out.mkdir(parents=True, exist_ok=True)
            for img, lab in frame_pairs(root, seq):
                if copy_images:
                    shutil.copy2(img, img_out / img.name)
                boxes = [b for b in (line_to_bbox(r) for r in _read_label_lines(lab)) if b]
                (lab_out / (img.stem + ".txt")).write_text(
                    "".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n"
                            for c, cx, cy, w, h in boxes)
                )
                n_img += 1
                n_box += len(boxes)
        manifest["splits"][split] = {
            "sequences": seqs, "images": n_img, "boxes": n_box,
        }

    yaml_path = out / "data.yaml"
    data = {
        "path": str(out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "nc": 1,
        "names": list(CLASS_NAMES),
    }
    with yaml_path.open("w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    manifest["data_yaml"] = str(yaml_path.resolve())
    return manifest


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
) -> None:
    """Append one run's metrics as a table row to RESULTS.md.

    ``dataset`` MUST identify the eval set (e.g. 'LettuceMOTS-val' or
    'own-frames'). Public and own-data metrics are logged as SEPARATE rows --
    never a single merged accuracy.
    """
    results_md = Path(results_md)
    row = (
        f"| {run} | {dataset} | {map50:.4f} | {map5095:.4f} | "
        f"{precision:.4f} | {recall:.4f} | {epochs} | {imgsz} |\n"
    )
    if not results_md.is_file() or _RESULTS_HEADER not in results_md.read_text():
        header = "# croprow RESULTS\n\nOne row per run. Public (LettuceMOTS) and own-frame\nmetrics are kept as separate rows -- never merged.\n\n" + _RESULTS_HEADER
        existing = results_md.read_text() if results_md.is_file() else ""
        results_md.write_text((existing + "\n" if existing else "") + header + row)
    else:
        with results_md.open("a") as fh:
            fh.write(row)
