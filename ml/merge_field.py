"""
merge_field.py — add pre-annotated field images into an existing YOLO split.

Run AFTER prepare_dataset.py has already built the base YOLO split.

Usage:
    python merge_field.py \
        --field-dir /kaggle/input/cropguard-field-potato \
        --out       /kaggle/working/datasets/potato_yolo \
        --seed      42 \
        --ratios    0.8 0.1 0.1
"""

import argparse
import random
import shutil
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


def parse_args():
    p = argparse.ArgumentParser(
        description="Merge pre-annotated field images into existing YOLO split"
    )
    p.add_argument(
        "--field-dir", required=True, type=Path,
        help="Flat field dataset folder containing images/ and labels/ subdirs",
    )
    p.add_argument(
        "--out", required=True, type=Path,
        help="Existing YOLO dataset dir (same --out used by prepare_dataset.py)",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducible split (default: 42)",
    )
    p.add_argument(
        "--ratios", type=float, nargs=3, default=[0.8, 0.1, 0.1],
        metavar=("TRAIN", "VAL", "TEST"),
        help="Train/val/test split ratios — must sum to 1.0 (default: 0.8 0.1 0.1)",
    )
    return p.parse_args()


def validate(args):
    errors = []

    if not args.field_dir.exists():
        errors.append(f"--field-dir not found: {args.field_dir}")
    else:
        if not (args.field_dir / "images").exists():
            errors.append(f"No images/ subdir in {args.field_dir}")
        if not (args.field_dir / "labels").exists():
            errors.append(f"No labels/ subdir in {args.field_dir}")

    if not args.out.exists():
        errors.append(
            f"--out directory not found: {args.out}\n"
            "  Run prepare_dataset.py first to build the base YOLO split."
        )

    if abs(sum(args.ratios) - 1.0) > 1e-6:
        errors.append(f"--ratios must sum to 1.0, got {sum(args.ratios):.4f}")

    for split in ("train", "valid", "test"):
        split_dir = args.out / split
        if args.out.exists() and not split_dir.exists():
            errors.append(
                f"Expected split directory not found: {split_dir}\n"
                "  Verify prepare_dataset.py completed successfully."
            )

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise SystemExit(1)


def collect_pairs(field_dir: Path):
    """
    Find valid image/label pairs in the flat field folder.
    Skips images with no paired .txt label and warns about them.
    Returns list of (image_path, label_path) tuples.
    """
    images_dir = field_dir / "images"
    labels_dir = field_dir / "labels"

    pairs = []
    skipped = []

    for img_path in sorted(images_dir.iterdir()):
        if img_path.suffix not in IMAGE_EXTENSIONS:
            continue
        label_path = labels_dir / (img_path.stem + ".txt")
        if not label_path.exists():
            skipped.append(img_path.name)
            continue
        pairs.append((img_path, label_path))

    if skipped:
        print(f"  WARNING: {len(skipped)} image(s) skipped — no paired label file:")
        for name in skipped[:10]:          # show at most 10
            print(f"    {name}")
        if len(skipped) > 10:
            print(f"    ... and {len(skipped) - 10} more")

    return pairs


def split_pairs(pairs, ratios, seed):
    """
    Shuffle with fixed seed and split into train/valid/test.
    Test gets the remainder to avoid losing images to rounding.
    """
    rng = random.Random(seed)
    shuffled = pairs[:]
    rng.shuffle(shuffled)

    n       = len(shuffled)
    n_train = int(n * ratios[0])
    n_val   = int(n * ratios[1])
    # n_test = remainder — no rounding loss

    return {
        "train": shuffled[:n_train],
        "valid": shuffled[n_train : n_train + n_val],
        "test":  shuffled[n_train + n_val :],
    }


def copy_pairs(split_dict, out_dir: Path):
    """Copy image/label pairs into the existing YOLO directory structure."""
    for split_name, pairs in split_dict.items():
        img_out = out_dir / split_name / "images"
        lbl_out = out_dir / split_name / "labels"
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        for img_path, lbl_path in pairs:
            shutil.copy2(img_path, img_out / img_path.name)
            shutil.copy2(lbl_path, lbl_out / lbl_path.name)

        print(f"  [{split_name:5s}] +{len(pairs)} pairs")


def main():
    args = parse_args()
    validate(args)

    print("=" * 55)
    print("merge_field.py")
    print(f"  Field dir : {args.field_dir}")
    print(f"  Output    : {args.out}")
    print(f"  Ratios    : train={args.ratios[0]}  val={args.ratios[1]}  test={args.ratios[2]}")
    print(f"  Seed      : {args.seed}")
    print("=" * 55)
    print()

    # ── 1. Collect ──────────────────────────────────────────
    print("Collecting image/label pairs...")
    pairs = collect_pairs(args.field_dir)
    print(f"  {len(pairs)} valid pairs found")
    print()

    # ── 2. Split ────────────────────────────────────────────
    print("Splitting...")
    split_dict = split_pairs(pairs, args.ratios, args.seed)
    for name, p in split_dict.items():
        print(f"  {name:5s} : {len(p)}")
    print()

    # ── 3. Copy ─────────────────────────────────────────────
    print("Copying into existing YOLO split...")
    copy_pairs(split_dict, args.out)

    print()
    print("Done. Field images merged into existing dataset.")
    print(f"Total field pairs added: {len(pairs)}")


if __name__ == "__main__":
    main()
