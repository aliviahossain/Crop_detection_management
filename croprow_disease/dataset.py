"""Adapter for a **provided** two-class (healthy / unhealthy) YOLO dataset.

``utils.py`` is built around LettuceMOTS: single-class segmentation polygons in
a ``train/images/<seq>/`` + ``LettuceMOTSyolo/<seq>/`` layout, from which it
derives boxes and colour-based health classes. That path is a *bootstrap* -- it
teaches the detector where plants are, but LettuceMOTS contains no affected
plants, so it cannot teach ``unhealthy``.

This module is the other path, and the one that matters once a real dataset
with both classes exists: take that dataset as it comes, validate it, and emit
the same ``data/health.yaml`` every downstream notebook (03-08) already reads.
Nothing downstream needs to change or even know which path produced the yaml.

Three layouts are accepted, covering essentially everything a labelling tool or
a public dataset ships:

``yaml``
    The dataset already has its own ``data.yaml`` / ``dataset.yaml``. Validated
    and adopted; images are not touched or copied.

``split``
    Standard Ultralytics tree, already split::

        <root>/images/train/...   <root>/labels/train/...
        <root>/images/val/...     <root>/labels/val/...

    (``valid`` and ``test`` are accepted as aliases for the val folder -- Roboflow
    exports use ``valid``.)

``flat``
    Images and labels side by side with no split::

        <root>/images/...    <root>/labels/...

    A train/val split is generated here, grouped so that frames from the same
    source clip stay on one side (see ``group_key``).

The one thing this module is strict about is **class order**. Ultralytics
matches classes by index, so a dataset whose names read ``[unhealthy, healthy]``
trains without complaint and inverts every prediction. ``validate_classes``
fails loudly on that rather than letting it through.
"""

from __future__ import annotations

import random
import shutil
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from .health import CLASS_NAMES, HEALTHY, UNHEALTHY

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
VAL_ALIASES = ("val", "valid", "validation", "test")

# Names a dataset might use for our two classes. Matching is case- and
# separator-insensitive, so "Healthy", "not_healthy" and "diseased" all land.
_HEALTHY_SYNONYMS = {"healthy", "good", "normal", "ok", "green"}
_UNHEALTHY_SYNONYMS = {
    "unhealthy", "nothealthy", "diseased", "disease", "sick", "damaged",
    "stressed", "infected", "blighted", "wilted", "dead", "dying", "brown",
    "bad", "off",
}


class DatasetError(RuntimeError):
    """Raised when a provided dataset cannot be used as-is."""


# --------------------------------------------------------------------------- #
# Class-name validation
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def canonical_class_name(name: str) -> str | None:
    """Map a dataset's class name onto ``healthy`` / ``unhealthy``, or None."""
    n = _norm(name)
    if n in {_norm(s) for s in _HEALTHY_SYNONYMS}:
        return "healthy"
    if n in {_norm(s) for s in _UNHEALTHY_SYNONYMS}:
        return "unhealthy"
    return None


def validate_classes(names: Sequence[str]) -> list[str]:
    """Check a dataset's class list against this module's fixed class order.

    Returns the canonical names on success. Raises ``DatasetError`` with an
    actionable message otherwise -- including the case that matters most, a
    dataset carrying the right two classes in the wrong order, where training
    would otherwise succeed and silently invert every prediction.
    """
    names = list(names)
    if len(names) != 2:
        raise DatasetError(
            f"Expected exactly 2 classes {CLASS_NAMES}, got {len(names)}: {names}.\n"
            "If the dataset has finer-grained classes (e.g. several diseases), "
            "remap them down to healthy/unhealthy first -- decide deliberately "
            "which of them count as unhealthy rather than letting index order "
            "choose for you."
        )

    canon = [canonical_class_name(n) for n in names]
    unknown = [n for n, c in zip(names, canon) if c is None]
    if unknown:
        raise DatasetError(
            f"Cannot tell which class these are: {unknown}.\n"
            f"Rename them to {CLASS_NAMES} in the dataset's yaml (index 0 = "
            "healthy, index 1 = unhealthy), or extend the synonym sets in "
            "croprow_disease/dataset.py if the naming is stable and meaningful."
        )
    if canon != CLASS_NAMES:
        raise DatasetError(
            f"Class ORDER mismatch: dataset has {names} (-> {canon}), this "
            f"module uses {CLASS_NAMES}.\n"
            "Ultralytics matches classes by INDEX, so training like this would "
            "invert every prediction without raising a single warning. Fix it "
            "by swapping the names in the dataset yaml AND remapping the first "
            "token of every label file (0 <-> 1) -- do both, or the labels stop "
            "matching the names."
        )
    return canon


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _images_under(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def label_for_image(img: Path, images_root: Path, labels_root: Path) -> Path:
    """The label file matching an image, mirroring the images tree."""
    return (labels_root / img.relative_to(images_root)).with_suffix(".txt")


def find_dataset_yaml(root: Path) -> Path | None:
    for name in ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml"):
        p = root / name
        if p.is_file():
            return p
    return None


def detect_layout(root: Path) -> str:
    """Classify a provided dataset root as ``yaml`` / ``split`` / ``flat``."""
    root = Path(root)
    if not root.is_dir():
        raise DatasetError(f"Dataset root does not exist or is not a dir: {root}")
    if find_dataset_yaml(root):
        return "yaml"
    images = root / "images"
    if images.is_dir():
        if (images / "train").is_dir() and any(
            (images / a).is_dir() for a in VAL_ALIASES
        ):
            return "split"
        return "flat"
    raise DatasetError(
        f"{root} looks like neither layout this module understands.\n"
        "Expected one of:\n"
        "  - a data.yaml at the root, or\n"
        "  - images/train + images/val (with a mirrored labels/ tree), or\n"
        "  - images/ + labels/ side by side (a split will be generated).\n"
        f"Found at the top level: {sorted(p.name for p in root.iterdir())[:12]}"
    )


def val_dir_name(images_root: Path) -> str:
    for alias in VAL_ALIASES:
        if (images_root / alias).is_dir():
            return alias
    raise DatasetError(
        f"No validation folder under {images_root} "
        f"(looked for {', '.join(VAL_ALIASES)})."
    )


# --------------------------------------------------------------------------- #
# Label inspection
# --------------------------------------------------------------------------- #
def scan_labels(
    images: Iterable[Path], images_root: Path, labels_root: Path
) -> dict:
    """Count instances per class and find structural problems.

    Reports images with no label file and images whose label file is empty
    separately: a missing label is usually a broken export, while an empty one
    is a legitimate negative (a frame with no plants) that Ultralytics accepts
    as a background image.
    """
    images = list(images)
    counts: Counter = Counter()
    missing: list[Path] = []
    empty: list[Path] = []
    bad_class: Counter = Counter()
    malformed: list[str] = []

    for img in images:
        lab = label_for_image(img, images_root, labels_root)
        if not lab.is_file():
            missing.append(img)
            continue
        lines = [l.strip() for l in lab.read_text().splitlines() if l.strip()]
        if not lines:
            empty.append(img)
            continue
        for line in lines:
            parts = line.split()
            if len(parts) != 5:
                malformed.append(f"{lab}: {len(parts)} tokens (expected 5)")
                continue
            try:
                cid = int(float(parts[0]))
            except ValueError:
                malformed.append(f"{lab}: non-numeric class id {parts[0]!r}")
                continue
            if cid in (HEALTHY, UNHEALTHY):
                counts[CLASS_NAMES[cid]] += 1
            else:
                bad_class[cid] += 1

    return {
        "images": len(images),
        "healthy": counts.get("healthy", 0),
        "unhealthy": counts.get("unhealthy", 0),
        "instances": sum(counts.values()),
        "missing_labels": missing,
        "empty_labels": empty,
        "out_of_range_class_ids": dict(bad_class),
        "malformed": malformed[:20],
        "malformed_total": len(malformed),
    }


# --------------------------------------------------------------------------- #
# Splitting (grouped -- never a naive per-frame shuffle)
# --------------------------------------------------------------------------- #
def group_key(img: Path, images_root: Path) -> str:
    """Which group an image belongs to for splitting purposes.

    Defaults to its immediate parent folder relative to the images root, which
    for video-derived data is the clip/sequence folder. If everything sits in
    one flat folder the key falls back to the filename stem's leading
    non-numeric part, so ``rowA_0001.jpg`` and ``rowA_0002.jpg`` group together.

    This matters: consecutive frames of one plant are near-identical, so a
    random per-image split puts nearly the same picture in train and val and
    reports a validation score that is really a training score.
    """
    rel = img.relative_to(images_root)
    if len(rel.parts) > 1:
        return str(Path(*rel.parts[:-1]))
    stem = img.stem
    prefix = stem.rstrip("0123456789-_ ")
    return prefix or stem


def split_grouped(
    images: Sequence[Path],
    images_root: Path,
    val_frac: float = 0.25,
    seed: int = 42,
) -> tuple[list[Path], list[Path]]:
    """Split images into (train, val) by group, never by individual frame.

    Groups are shuffled and taken until the val side reaches ``val_frac`` of the
    images; at least one group is guaranteed to each side. Falls back to an
    image-level split only when the whole dataset is a single group, and warns
    when it does -- leaking silently would be worse.
    """
    groups: dict[str, list[Path]] = {}
    for img in images:
        groups.setdefault(group_key(img, images_root), []).append(img)

    if len(groups) < 2:
        import warnings
        warnings.warn(
            f"Only one group ({next(iter(groups), 'n/a')}) -- falling back to an "
            "image-level split. If these are video frames, adjacent frames will "
            "leak across train/val and the val score will be optimistic. Put "
            "each clip in its own subfolder to fix.",
            RuntimeWarning, stacklevel=2,
        )
        shuffled = list(images)
        random.Random(seed).shuffle(shuffled)
        n_val = max(1, min(len(shuffled) - 1, round(len(shuffled) * val_frac)))
        return sorted(shuffled[n_val:]), sorted(shuffled[:n_val])

    names = sorted(groups)
    random.Random(seed).shuffle(names)
    target = val_frac * len(images)
    val_groups: list[str] = []
    n_val = 0
    for name in names:
        if n_val >= target and val_groups:
            break
        if len(val_groups) == len(names) - 1:
            break                       # always keep one group for train
        val_groups.append(name)
        n_val += len(groups[name])

    val_set = set(val_groups)
    train = sorted(p for g, ps in groups.items() if g not in val_set for p in ps)
    val = sorted(p for g in val_groups for p in groups[g])
    return train, val


# --------------------------------------------------------------------------- #
# The one entry point the notebooks call
# --------------------------------------------------------------------------- #
def prepare_provided_dataset(
    root: Path,
    data_dir: Path,
    val_frac: float = 0.25,
    seed: int = 42,
    yaml_name: str = "health.yaml",
    strict: bool = True,
) -> dict:
    """Validate a provided 2-class dataset and emit ``data_dir/health.yaml``.

    Detects the layout, checks class names and order, scans every label file,
    generates a grouped train/val split if the dataset has none, and writes the
    same yaml (plus ``train.txt`` / ``val.txt`` list files) that the LettuceMOTS
    path produces -- so notebooks 03-08 work unchanged either way.

    Images are never copied or modified; the list files point at them in place.

    ``strict=True`` refuses a dataset with missing label files, out-of-range
    class ids, or an empty class. Those are real defects: a missing label reads
    to Ultralytics as "this image contains nothing", which actively teaches the
    model to miss plants. Set it False only after reading the report and
    deciding the damage is acceptable.

    Returns a report dict.
    """
    root = Path(root)
    data_dir = Path(data_dir)
    layout = detect_layout(root)
    report: dict = {"root": str(root.resolve()), "layout": layout,
                    "warnings": [], "errors": []}

    # --- resolve images/labels roots and the split ------------------------- #
    if layout == "yaml":
        src_yaml = find_dataset_yaml(root)
        cfg = yaml.safe_load(Path(src_yaml).read_text()) or {}
        report["source_yaml"] = str(src_yaml)
        names = cfg.get("names")
        if isinstance(names, dict):            # e.g. {0: healthy, 1: unhealthy}
            names = [names[k] for k in sorted(names, key=lambda x: int(x))]
        validate_classes(names or [])
        base = Path(cfg.get("path") or root)
        if not base.is_absolute():
            base = (root / base).resolve()

        def _resolve(entry) -> list[Path]:
            p = Path(entry)
            if not p.is_absolute():
                p = base / p
            if p.is_file():                    # a .txt list of image paths
                return [Path(l) for l in p.read_text().splitlines() if l.strip()]
            return _images_under(p)

        train_imgs = _resolve(cfg["train"])
        val_imgs = _resolve(cfg.get("val") or cfg.get("valid") or cfg["train"])
        images_root = base / "images" if (base / "images").is_dir() else base
        labels_root = base / "labels" if (base / "labels").is_dir() else base

    elif layout == "split":
        images_root, labels_root = root / "images", root / "labels"
        if not labels_root.is_dir():
            raise DatasetError(f"No labels/ tree next to {images_root}.")
        val_name = val_dir_name(images_root)
        train_imgs = _images_under(images_root / "train")
        val_imgs = _images_under(images_root / val_name)
        report["val_dir"] = val_name

    else:  # flat
        images_root, labels_root = root / "images", root / "labels"
        if not labels_root.is_dir():
            raise DatasetError(f"No labels/ tree next to {images_root}.")
        all_imgs = _images_under(images_root)
        if not all_imgs:
            raise DatasetError(f"No images found under {images_root}.")
        train_imgs, val_imgs = split_grouped(all_imgs, images_root, val_frac, seed)
        report["generated_split"] = True
        report["groups"] = sorted({group_key(p, images_root) for p in all_imgs})

    if not train_imgs:
        raise DatasetError(f"No training images found under {root}.")
    if not val_imgs:
        raise DatasetError(f"No validation images found under {root}.")

    # --- scan labels ------------------------------------------------------- #
    for split, imgs in (("train", train_imgs), ("val", val_imgs)):
        scan = scan_labels(imgs, images_root, labels_root)
        scan["missing_labels"] = [str(p) for p in scan["missing_labels"][:10]]
        scan["empty_labels"] = len(scan["empty_labels"])
        report[split] = scan

    overlap = set(train_imgs) & set(val_imgs)
    if overlap:
        report["errors"].append(
            f"{len(overlap)} image(s) appear in BOTH train and val -- the val "
            "score would be meaningless. First few: "
            f"{[str(p) for p in list(overlap)[:5]]}")

    for split in ("train", "val"):
        s = report[split]
        if s["missing_labels"]:
            report["errors"].append(
                f"{split}: {len(s['missing_labels'])}+ image(s) have no label "
                "file. Ultralytics reads those as empty, teaching the model to "
                f"miss plants. First: {s['missing_labels'][:3]}")
        if s["out_of_range_class_ids"]:
            report["errors"].append(
                f"{split}: label files contain class ids outside 0/1: "
                f"{s['out_of_range_class_ids']}. Remap them before training.")
        if s["malformed_total"]:
            report["errors"].append(
                f"{split}: {s['malformed_total']} malformed label line(s). "
                f"First: {s['malformed'][:3]}")
        if s["empty_labels"]:
            report["warnings"].append(
                f"{split}: {s['empty_labels']} image(s) have an empty label file "
                "-- fine if they are genuine background frames, a bug if not.")
        if s["unhealthy"] == 0:
            report["errors"].append(
                f"{split}: ZERO unhealthy instances. A two-class model cannot be "
                "trained or validated on this split.")
        elif s["healthy"] == 0:
            report["errors"].append(f"{split}: ZERO healthy instances.")

    if strict and report["errors"]:
        raise DatasetError(
            "Provided dataset is not usable as-is:\n  - "
            + "\n  - ".join(report["errors"])
            + "\n\nFix these, or pass strict=False to proceed deliberately."
        )

    # --- emit list files + yaml -------------------------------------------- #
    data_dir.mkdir(parents=True, exist_ok=True)
    for split, imgs in (("train", train_imgs), ("val", val_imgs)):
        p = data_dir / f"{split}.txt"
        p.write_text("\n".join(str(Path(i).resolve()) for i in imgs) + "\n")
        report[f"{split}_list"] = str(p)

    yaml_path = data_dir / yaml_name
    yaml_path.write_text(yaml.safe_dump({
        "train": str((data_dir / "train.txt").resolve()),
        "val": str((data_dir / "val.txt").resolve()),
        "nc": len(CLASS_NAMES),
        "names": list(CLASS_NAMES),
    }, sort_keys=False))
    report["data_yaml"] = str(yaml_path.resolve())
    report["images_root"] = str(Path(images_root).resolve())
    report["labels_root"] = str(Path(labels_root).resolve())
    return report


def format_report(report: dict) -> str:
    """Human-readable summary of ``prepare_provided_dataset``."""
    lines = [
        f"layout      : {report['layout']}",
        f"root        : {report['root']}",
    ]
    if report.get("generated_split"):
        lines.append(f"split       : generated, grouped by "
                     f"{len(report.get('groups', []))} group(s)")
    for split in ("train", "val"):
        s = report.get(split)
        if not s:
            continue
        lines.append(
            f"{split:12s}: {s['images']:5d} images | healthy {s['healthy']:6d} | "
            f"unhealthy {s['unhealthy']:6d}")
    total_u = sum(report[s]["unhealthy"] for s in ("train", "val") if s in report)
    total_h = sum(report[s]["healthy"] for s in ("train", "val") if s in report)
    total = total_h + total_u
    if total:
        lines.append(f"{'balance':12s}: healthy {100 * total_h / total:.1f}% / "
                     f"unhealthy {100 * total_u / total:.1f}%")
    for w in report.get("warnings", []):
        lines.append(f"WARNING     : {w}")
    for e in report.get("errors", []):
        lines.append(f"ERROR       : {e}")
    if report.get("data_yaml"):
        lines.append(f"data yaml   : {report['data_yaml']}")
    return "\n".join(lines)
