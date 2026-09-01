"""Build the potato YOLO detection dataset (3 classes), stratified and balanced.

Run this on Kaggle, never on the dev laptop -- PlantVillage is ~2 GB and the
brief pins a machine with very little C: space.

Why this script is more than a file copy
----------------------------------------

**1. Stratified splits, not a random split.** PlantVillage potato is badly
imbalanced (roughly 1000 / 1000 / 152 for early blight / late blight /
healthy). A random 80/10/10 on 152 healthy images can easily leave a val split
with a handful of them, at which point the healthy-class metric is noise and
you cannot tell whether the model learnt the class or not. Splits here are
assigned per class with exact quotas, and the script refuses to proceed
quietly if any class ends up with too few validation images.

**2. Balancing happens on the train split only.** Capping the majority classes
is right for training; doing it to val/test would throw away the evaluation
data you need most. Minority classes can be oversampled by repetition
(`--oversample-min`), which combined with YOLO's per-epoch augmentation gives
the model varied views rather than identical duplicates.

**3. Deterministic.** Split assignment is by content hash, so an image keeps
its split across reruns, val scores stay comparable, and nothing leaks from
train into val when you re-run with different flags.

**4. Lab vs field evaluation lists.** Images keep a `pv_` (lab) or `ann_`
(field) prefix, and the script writes `val_lab.txt` / `val_field.txt` so
`ml/evaluate.py` can report the two separately. A lab-only mAP is not a field
mAP, and this makes the difference visible instead of quotable.

Sources
-------
1. **PlantVillage potato folders** -- a *classification* dataset: one leaf,
   uniform background, no boxes. We generate a weak full-frame box. Standard
   weak supervision, honest about what it is.
2. **A real annotated detection export** (PlantDoc potato subset, or your own
   Roboflow project in YOLO format). Field-condition images with real boxes.
   These take priority and are what makes the model survive a phone photo.

Usage
-----
    python ml/prepare_dataset.py \
        --plantvillage /kaggle/input/plantvillage-dataset/color \
        --annotated    /kaggle/input/potato-field-yolo \
        --out          /kaggle/working/potato_yolo \
        --cap-train 400 --oversample-min
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Authoritative order -- must match ml/data.yaml and taxonomy.CLASS_NAMES.
CLASS_NAMES = ["potato_early_blight", "potato_late_blight", "potato_healthy"]
CLASS_INDEX = {name: i for i, name in enumerate(CLASS_NAMES)}

# Only potato is taken; every other PlantVillage crop folder is ignored.
PLANTVILLAGE_MAP = {
    "Potato___Early_blight": "potato_early_blight",
    "Potato___Late_blight": "potato_late_blight",
    "Potato___healthy": "potato_healthy",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
SPLITS = ("train", "val", "test")
# Weak box covers the centre 90%: the leaf fills a PlantVillage frame, and the
# small inset stops the model learning "box == whole image".
WEAK_BOX = (0.5, 0.5, 0.90, 0.90)

# Below this many val images, a per-class metric is noise rather than a measurement.
MIN_VAL_PER_CLASS = 20
# ...but never spend more than this share of a class on val (or on test).
MAX_EVAL_FRACTION = 0.25
# Train imbalance above this ratio measurably skews predictions toward the majority.
MAX_TRAIN_IMBALANCE = 1.5
# Above this share of duplicated images, a class is being held up by
# augmentation rather than by data.
MAX_DUPLICATE_SHARE = 0.6


@dataclass
class Record:
    src: Path
    class_key: str
    source: str  # "pv" (lab) or "ann" (field)
    label_lines: list[str]

    @property
    def stem(self) -> str:
        return f"{self.source}_{self.class_key}_{self.src.stem}"


# 12 hex characters = 48 bits, so the divisor must be 2**48, not a hand-typed
# run of F's. Getting this wrong returned values up to 16.0 while the docstring
# promised [0,1) -- harmless for sorting, silent garbage the moment anyone
# writes `if hash_unit(...) < 0.8`.
_HASH_HEX_CHARS = 12
_HASH_SCALE = float(1 << (4 * _HASH_HEX_CHARS))


def hash_unit(key: str) -> float:
    """Deterministic value in [0,1) -- an image keeps its split across reruns."""
    digest = hashlib.sha256(key.encode()).hexdigest()[:_HASH_HEX_CHARS]
    return int(digest, 16) / _HASH_SCALE


# ----------------------------------------------------------------------
# Collection
# ----------------------------------------------------------------------
def collect_plantvillage(src: Path) -> list[Record]:
    cx, cy, w, h = WEAK_BOX
    records: list[Record] = []
    for folder, class_key in PLANTVILLAGE_MAP.items():
        class_dir = src / folder
        if not class_dir.is_dir():
            print(f"  ! missing {class_dir}, skipping", file=sys.stderr)
            continue
        for img in sorted(class_dir.iterdir()):
            if img.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            records.append(
                Record(
                    src=img,
                    class_key=class_key,
                    source="pv",
                    label_lines=[f"{CLASS_INDEX[class_key]} {cx} {cy} {w} {h}"],
                )
            )
    return records


# ----------------------------------------------------------------------
# Mapping a third-party dataset's classes onto ours
# ----------------------------------------------------------------------
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise_class_name(raw: str) -> str:
    """`Potato___Early_blight` / `Potato leaf early blight` -> `potato early blight`."""
    return _NON_ALNUM.sub(" ", str(raw).lower()).strip()


def map_source_class(raw: str) -> str | None:
    """Map a PlantDoc / Roboflow class name onto one of our three keys.

    Returns None for anything it cannot map confidently -- every other crop in
    PlantDoc, and any ambiguous potato label like "potato leaf blight" that does
    not say early or late. Guessing at an ambiguous name is how you silently
    train early blight images as late blight.
    """
    tokens = normalise_class_name(raw)
    if "potato" not in tokens:
        return None
    if "early" in tokens:
        return "potato_early_blight"
    if "late" in tokens:
        return "potato_late_blight"
    # PlantDoc calls the healthy class simply "Potato leaf".
    if "healthy" in tokens or tokens in {"potato leaf", "potato", "potato leaves"}:
        return "potato_healthy"
    return None


def derive_remap(source_names: list[str]) -> tuple[dict[int, int], list[str], list[str]]:
    """Build a source-index -> our-index map from the source's own class names.

    Name-based mapping instead of a hand-typed `--remap 0=1,1=0`. Index
    remapping is the same failure mode as a mismatched data.yaml: nothing
    detects it, and every image from that source is trained under the wrong
    label. The source dataset already ships its names; use them.
    """
    remap: dict[int, int] = {}
    mapped: list[str] = []
    dropped: list[str] = []
    for idx, name in enumerate(source_names):
        target = map_source_class(name)
        if target is None:
            dropped.append(name)
            continue
        remap[idx] = CLASS_INDEX[target]
        mapped.append(f"{name} -> {target}")
    return remap, mapped, dropped


def read_yaml_names(path: Path) -> list[str]:
    """Read a YOLO data.yaml `names:` block, list or dict form, without PyYAML."""
    text = path.read_text(encoding="utf-8")
    # `[ \t]*` not `\s*`: \s matches newlines, so the greedy version swallowed
    # the line break and the first indented entry with it, silently returning a
    # names list one class short and off by one.
    block = re.search(r"^names:[ \t]*(.*)$", text, re.M)
    if not block:
        return []
    inline = block.group(1).strip()
    if inline.startswith("["):
        return [n.strip().strip("'\"") for n in inline[1:-1].split(",") if n.strip()]

    names: list[tuple[int, str]] = []
    ordered: list[str] = []
    after = text[block.end() :]
    for line in after.splitlines():
        m_idx = re.match(r"^\s+(\d+)\s*:\s*(.+?)\s*$", line)
        m_item = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if m_idx:
            names.append((int(m_idx.group(1)), m_idx.group(2).strip("'\"")))
        elif m_item:
            ordered.append(m_item.group(1).strip("'\""))
        elif line.strip() and not line.startswith((" ", "\t", "-")):
            break
    if names:
        return [n for _, n in sorted(names)]
    return ordered


def find_source_yaml(src: Path) -> Path | None:
    """Locate the data.yaml a Roboflow/PlantDoc export ships with."""
    for candidate in ("data.yaml", "data.yml"):
        direct = src / candidate
        if direct.exists():
            return direct
    matches = sorted(src.glob(f"**/data.y*ml"))
    return matches[0] if matches else None


def _labels_dir_for(img: Path) -> Path | None:
    """Map `.../images/<split>/` to `.../labels/<split>/`.

    Rewrites only the LAST path component that is exactly `images`. The obvious
    `str(path).replace("images", "labels")` is wrong twice over: it replaces
    every occurrence, and it matches inside names. A perfectly ordinary Kaggle
    input path like `/kaggle/input/potato-images/images/train/leaf.jpg` becomes
    `/kaggle/input/potato-labels/labels/train/leaf.jpg` -- a directory that does
    not exist, so every image is skipped and the run reports zero records with
    no error at all.
    """
    parts = list(img.parent.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            return Path(*parts)
    return None


def _find_label(img: Path, root: Path) -> Path | None:
    candidates = [img.with_suffix(".txt")]
    labels_dir = _labels_dir_for(img)
    if labels_dir is not None:
        candidates.append(labels_dir / f"{img.stem}.txt")
    candidates.append(root / "labels" / f"{img.stem}.txt")
    candidates.append(root / "labels" / img.parent.name / f"{img.stem}.txt")
    return next((c for c in candidates if c.exists()), None)


def collect_annotated(src: Path, remap: dict[int, int] | None) -> list[Record]:
    """Ingest a real YOLO detection export, preserving its boxes."""
    records: list[Record] = []
    images = [p for p in src.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        print(f"  ! no images found under {src}", file=sys.stderr)
        return records

    missing_label = 0
    empty_label = 0
    for img in images:
        label = _find_label(img, src)
        if label is None:
            missing_label += 1
            continue
        lines: list[str] = []
        for line in label.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            cls_id = int(float(parts[0]))
            if remap is not None:
                if cls_id not in remap:
                    continue  # outside our 3-class potato scope
                cls_id = remap[cls_id]
            if cls_id >= len(CLASS_NAMES):
                continue
            lines.append(" ".join([str(cls_id), *parts[1:5]]))
        if not lines:
            empty_label += 1
            continue
        # Stratify a multi-box image by its dominant class, so field images are
        # split by content rather than by filename luck.
        dominant = Counter(int(l.split()[0]) for l in lines).most_common(1)[0][0]
        records.append(
            Record(
                src=img,
                class_key=CLASS_NAMES[dominant],
                source="ann",
                label_lines=lines,
            )
        )

    # Silence here is what made the path bug invisible: a wrong labels/ directory
    # skips every image and the script carries on as if the input were empty.
    print(f"  {len(records)} of {len(images)} annotated images had usable labels.")
    if missing_label:
        print(
            f"  ! {missing_label} image(s) had no matching .txt label file.",
            file=sys.stderr,
        )
    if empty_label:
        print(
            f"  ! {empty_label} image(s) had labels but no boxes inside the 3-class "
            "potato scope (check --remap).",
            file=sys.stderr,
        )
    if not records:
        print(
            f"  ! NO usable annotations found under {src}. Expected a YOLO layout with a "
            "labels/ directory alongside images/. Nothing from --annotated will be used.",
            file=sys.stderr,
        )
    return records


# ----------------------------------------------------------------------
# Stratified splitting
# ----------------------------------------------------------------------
def stratified_split(
    records: list[Record], ratios: tuple[float, float, float]
) -> dict[str, list[Record]]:
    """Assign exact per-class quotas, deterministically.

    Each (class, source) group is sorted by content hash and cut at exact
    positions. Compared with hashing each image independently, this guarantees
    the rare healthy class gets its full 10% in val instead of whatever the
    hash happened to give -- which is the difference between measuring that
    class and guessing at it.
    """
    out: dict[str, list[Record]] = {s: [] for s in SPLITS}
    groups: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for rec in records:
        groups[(rec.class_key, rec.source)].append(rec)

    for (class_key, source), items in sorted(groups.items()):
        items.sort(key=lambda r: hash_unit(f"{source}/{class_key}/{r.src.name}"))
        n = len(items)
        n_val = max(1, round(n * ratios[1])) if n >= 3 else 0
        n_test = max(1, round(n * ratios[2])) if n >= 3 else 0

        # A small class gets a larger val share, up to MAX_EVAL_FRACTION of it.
        # PlantVillage has only ~152 healthy potato images: a flat 10% leaves 15
        # val images, and a per-class metric off 15 images is noise. Spending a
        # few more on evaluation buys a number you can actually trust.
        ceiling = int(n * MAX_EVAL_FRACTION)
        if 0 < n_val < MIN_VAL_PER_CLASS and ceiling >= MIN_VAL_PER_CLASS:
            n_val = MIN_VAL_PER_CLASS
        if 0 < n_test < MIN_VAL_PER_CLASS and ceiling >= MIN_VAL_PER_CLASS:
            n_test = MIN_VAL_PER_CLASS

        if n_val + n_test >= n:  # tiny group: keep at least one training image
            n_val, n_test = (1, 0) if n >= 2 else (0, 0)
        out["val"] += items[:n_val]
        out["test"] += items[n_val : n_val + n_test]
        out["train"] += items[n_val + n_test :]
    return out


def balance_train(
    train: list[Record], cap: int | None, oversample_min: bool
) -> tuple[list[Record], dict]:
    """Cap majority classes and optionally oversample the minority.

    Applied to the train split only. Doing this to val/test would corrupt the
    evaluation set -- you would be measuring on a distribution you invented.
    """
    by_class: dict[str, list[Record]] = defaultdict(list)
    for rec in train:
        by_class[rec.class_key].append(rec)

    before = {k: len(v) for k, v in by_class.items()}

    if cap:
        for class_key, items in by_class.items():
            if len(items) > cap:
                # Deterministic subsample, so a rerun keeps the same images.
                items.sort(key=lambda r: hash_unit(f"cap/{class_key}/{r.src.name}"))
                by_class[class_key] = items[:cap]

    duplicated = 0
    if oversample_min and by_class:
        target = max(len(v) for v in by_class.values())
        for class_key, items in by_class.items():
            if not items or len(items) >= target:
                continue
            # Repeat the minority class up to the majority count. YOLO applies
            # fresh augmentation per epoch, so repeats are not identical views.
            need = target - len(items)
            by_class[class_key] = items + [items[i % len(items)] for i in range(need)]
            duplicated += need

    balanced = [rec for items in by_class.values() for rec in items]
    after = {k: len(v) for k, v in by_class.items()}
    return balanced, {"before": before, "after": after, "duplicated": duplicated}


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def write_split(out: Path, split: str, records: list[Record]) -> list[Path]:
    img_dir = out / "images" / split
    lbl_dir = out / "labels" / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen: Counter = Counter()
    for rec in records:
        stem = rec.stem
        seen[stem] += 1
        if seen[stem] > 1:  # oversampled duplicate needs its own filename
            stem = f"{stem}__dup{seen[stem] - 1}"
        dest = img_dir / f"{stem}{rec.src.suffix.lower()}"
        shutil.copy2(rec.src, dest)
        (lbl_dir / f"{stem}.txt").write_text(
            "\n".join(rec.label_lines) + "\n", encoding="utf-8"
        )
        written.append(dest)
    return written


def write_yamls(out: Path, val_paths: list[Path]) -> None:
    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASS_NAMES))
    (out / "data.yaml").write_text(
        f"path: {out.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n\n"
        f"names:\n{names}\n",
        encoding="utf-8",
    )

    # Per-source val lists, so lab and field performance can be reported
    # separately. Ultralytics accepts a .txt file of image paths as a split.
    for source, label in (("pv_", "lab"), ("ann_", "field")):
        subset = [p for p in val_paths if p.name.startswith(source)]
        if not subset:
            continue
        list_path = out / f"val_{label}.txt"
        list_path.write_text(
            "\n".join(p.as_posix() for p in subset) + "\n", encoding="utf-8"
        )
        (out / f"data_{label}.yaml").write_text(
            f"path: {out.as_posix()}\n"
            "train: images/train\n"
            f"val: {list_path.name}\n\n"
            f"names:\n{names}\n",
            encoding="utf-8",
        )


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------
def report(splits: dict[str, list[Record]], balance_info: dict, out: Path) -> int:
    print("\nSplit composition")
    print("-" * 72)
    print(f"  {'class':<24}{'train':>8}{'val':>8}{'test':>8}{'lab':>8}{'field':>8}")
    counts = {
        s: Counter(r.class_key for r in recs) for s, recs in splits.items()
    }
    source_counts = Counter(
        (r.class_key, r.source) for recs in splits.values() for r in recs
    )
    for cls in CLASS_NAMES:
        print(
            f"  {cls:<24}"
            f"{counts['train'][cls]:>8}{counts['val'][cls]:>8}{counts['test'][cls]:>8}"
            f"{source_counts[(cls, 'pv')]:>8}{source_counts[(cls, 'ann')]:>8}"
        )
    total = sum(len(v) for v in splits.values())
    print(f"  {'TOTAL':<24}{len(splits['train']):>8}{len(splits['val']):>8}"
          f"{len(splits['test']):>8}{'':>8}{'':>8}   ({total} images)")

    warnings = 0
    warnings_from_balance: list[str] = []

    print("\nClass balance (train split)")
    print("-" * 72)
    before, after = balance_info["before"], balance_info["after"]
    for cls in CLASS_NAMES:
        b, a = before.get(cls, 0), after.get(cls, 0)
        arrow = "->" if b != a else "  "
        print(f"  {cls:<24}{b:>8} {arrow} {a:>8}")
    if balance_info["duplicated"]:
        print(f"  ({balance_info['duplicated']} oversampled repeats added)")

    # Oversampling is not free. Repeating 112 healthy images up to 400 means 72%
    # of that class's training data is duplicates, and every bit of the variety
    # has to come from augmentation. Worth doing, worth knowing the number.
    for cls in CLASS_NAMES:
        unique = before.get(cls, 0)
        total_after = after.get(cls, 0)
        if total_after > unique > 0:
            dup_share = (total_after - unique) / total_after
            print(
                f"  {cls}: {unique} unique image(s) repeated to {total_after} "
                f"({dup_share:.0%} duplicates)"
            )
            if dup_share > MAX_DUPLICATE_SHARE:
                print(
                    f"  WARNING: {dup_share:.0%} of the {cls} training split is duplicated "
                    f"from only {unique} unique images. Augmentation is carrying that class "
                    "almost entirely - expect it to overfit.\n"
                    "           The real fix is more source images for it, not more repeats.",
                    file=sys.stderr,
                )
                warnings_from_balance.append(cls)

    if after and min(after.values()) > 0:
        ratio_before = max(before.values()) / max(min(before.values()), 1)
        ratio_after = max(after.values()) / min(after.values())
        print(f"\n  imbalance ratio: {ratio_before:.2f}:1  ->  {ratio_after:.2f}:1")
        if ratio_after > MAX_TRAIN_IMBALANCE:
            print(
                f"  WARNING: train imbalance is still {ratio_after:.2f}:1. The model will "
                f"under-predict the minority class.\n"
                f"           Use --cap-train {min(after.values())} or --oversample-min.",
                file=sys.stderr,
            )
            warnings += 1

    print("\nValidation adequacy")
    print("-" * 72)
    for cls in CLASS_NAMES:
        n = counts["val"][cls]
        status = "ok" if n >= MIN_VAL_PER_CLASS else "TOO FEW"
        print(f"  {cls:<24}{n:>8} val images   {status}")
        if n < MIN_VAL_PER_CLASS:
            print(
                f"  WARNING: {cls} has {n} validation images (< {MIN_VAL_PER_CLASS}). Its "
                f"per-class metric will be noise, not a measurement.",
                file=sys.stderr,
            )
            warnings += 1

    field_val = sum(1 for r in splits["val"] if r.source == "ann")
    print(f"\n  field-condition val images: {field_val}")
    if field_val == 0:
        print(
            "  WARNING: no field-condition images. Every metric this run produces is a "
            "LAB metric.\n"
            "           A model trained only on PlantVillage learns 'leaf on grey "
            "background' and\n"
            "           degrades on real phone photos. Add --annotated before quoting "
            "field accuracy.",
            file=sys.stderr,
        )
        warnings += 1

    manifest = {
        "classes": CLASS_NAMES,
        "counts": {s: dict(counts[s]) for s in SPLITS},
        "by_source": {
            f"{cls}/{src}": n for (cls, src), n in sorted(source_counts.items())
        },
        "balance": {
            **balance_info,
            # Only oversampling creates duplicates. A capped class has fewer
            # images than it started with, which is not negative duplication.
            "duplicate_share": {
                cls: round(
                    max(
                        0,
                        balance_info["after"].get(cls, 0)
                        - balance_info["before"].get(cls, 0),
                    )
                    / balance_info["after"][cls],
                    3,
                )
                for cls in CLASS_NAMES
                if balance_info["after"].get(cls, 0) > 0
            },
            "heavily_duplicated_classes": warnings_from_balance,
        },
        "field_val_images": field_val,
        "warnings": warnings,
    }
    warnings += len(warnings_from_balance)

    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest -> {out / 'dataset_manifest.json'}")
    return warnings


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--plantvillage", type=Path, help="PlantVillage 'color' directory")
    ap.add_argument("--annotated", type=Path, help="Real YOLO-format detection export (field images)")
    ap.add_argument(
        "--remap",
        type=str,
        default=None,
        help="Manual override, e.g. '0=1,1=0' (source=ours). By default the mapping is "
             "derived from the source data.yaml class NAMES, which is safer.",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ratios", type=float, nargs=3, default=(0.8, 0.1, 0.1))
    ap.add_argument(
        "--cap-train", type=int, default=None,
        help="Cap each class in the TRAIN split. val/test are never capped.",
    )
    ap.add_argument(
        "--oversample-min", action="store_true",
        help="Repeat minority-class train images up to the majority count.",
    )
    ap.add_argument("--clean", action="store_true", help="Delete --out first")
    args = ap.parse_args()

    if not args.plantvillage and not args.annotated:
        ap.error("Give at least one of --plantvillage or --annotated")

    # Unvalidated ratios silently produce a split that is not the one asked for
    # -- and the quota arithmetic below assumes they sum to 1.
    if any(r < 0 for r in args.ratios):
        ap.error("--ratios values must not be negative")
    ratio_sum = sum(args.ratios)
    if abs(ratio_sum - 1.0) > 1e-6:
        ap.error(
            f"--ratios must sum to 1.0, got {ratio_sum:g} "
            f"({args.ratios[0]:g} train / {args.ratios[1]:g} val / {args.ratios[2]:g} test)"
        )
    if args.ratios[0] <= 0:
        ap.error("--ratios needs a non-zero train share")

    out: Path = args.out
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    records: list[Record] = []
    if args.plantvillage:
        print(f"Collecting PlantVillage potato classes from {args.plantvillage}")
        records += collect_plantvillage(args.plantvillage)
    if args.annotated:
        remap = None
        if args.remap:
            remap = {int(k): int(v) for k, v in (p.split("=") for p in args.remap.split(","))}
            print(f"  using manual --remap {remap}")
        else:
            source_yaml = find_source_yaml(args.annotated)
            if source_yaml is None:
                print(
                    f"  ! no data.yaml found under {args.annotated}. Class indices will be "
                    "taken as-is, which is only correct if the source already uses our order. "
                    "Pass --remap explicitly if it does not.",
                    file=sys.stderr,
                )
            else:
                source_names = read_yaml_names(source_yaml)
                remap, mapped, dropped = derive_remap(source_names)
                print(f"  read {len(source_names)} class name(s) from {source_yaml.name}")
                for line in mapped:
                    print(f"    mapped:  {line}")
                if dropped:
                    print(f"    dropped: {len(dropped)} non-potato/ambiguous class(es)")
                    for name in dropped[:6]:
                        print(f"             {name}")
                if not remap:
                    print(
                        "  ! no source class mapped onto our three potato classes. Check the "
                        "export's names, or pass --remap manually.",
                        file=sys.stderr,
                    )
        print(f"Collecting annotated detection data from {args.annotated}")
        records += collect_annotated(args.annotated, remap)

    if not records:
        print("\nNo images collected - check the input paths.", file=sys.stderr)
        return 1
    print(f"Collected {len(records)} images.")

    splits = stratified_split(records, tuple(args.ratios))
    splits["train"], balance_info = balance_train(
        splits["train"], args.cap_train, args.oversample_min
    )

    val_paths: list[Path] = []
    for split in SPLITS:
        written = write_split(out, split, splits[split])
        if split == "val":
            val_paths = written
    write_yamls(out, val_paths)

    warnings = report(splits, balance_info, out)
    print(f"\ndata.yaml -> {out / 'data.yaml'}")
    if (out / "data_field.yaml").exists():
        print(f"Per-source eval: {out / 'data_lab.yaml'}, {out / 'data_field.yaml'}")
    if warnings:
        print(f"\nCompleted with {warnings} warning(s) - read them before training.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
