# Dataset choice and provenance

Which dataset you train on determines what the model actually learns. This
records the options, their real sizes, and why the pipeline defaults the way it
does — so the decision is reviewable rather than inherited.

## The three-class requirement

The deployed system needs **potato_early_blight, potato_late_blight,
potato_healthy**. The healthy class is not optional decoration: it is the class
that lets the system say *"do not spray"*, which is the core of the problem
statement's "more targeted pesticide use". A dataset without a potato-specific
healthy class cannot supply it.

## Options compared

| | **PlantVillage** (default) | **PlantDoc** | **Roboflow "Plant Diseases Detection and Classification"** |
|---|---|---|---|
| Potato images | ~2,150 (1000 / 1000 / 152) | low hundreds | ~2,600 total across **10** classes, so a few hundred potato |
| Potato classes | Early, Late, **Healthy** | Early, Late, Healthy | Early, Late — **no potato-specific healthy** |
| Conditions | Lab: one leaf, uniform grey background | **Real field conditions** | Mixed |
| Task type | Classification (no boxes) | Detection (real boxes) | Detection (real boxes) |
| Provenance | ICAR/Penn State, widely cited, peer-reviewed | Published paper (Singh et al., CoDS-COMAD 2020) | Unverified 2023 student graduation project |
| Role here | **Volume base** | **Realism** — merge this in | Reference for pipeline structure only |

### Why PlantVillage is the base and not the Roboflow set

The Roboflow dataset behind [muqadasejaz/Plant-Detection-using-YOLOv8](https://github.com/muqadasejaz/Plant-Detection-using-YOLOv8)
is a reasonable structural reference — Roboflow → notebook → `best.pt` → inference
is the right shape of pipeline. As a *dataset* for this project it is the weaker
choice:

1. **Volume.** ~2,600 images spread over 10 classes. Filtering to potato leaves
   a few hundred images across two classes — against PlantVillage's ~2,000 for
   the same two classes.
2. **It has no potato healthy class.** Its healthy category is a generic
   "Healthy Leaf" spanning apple, corn, tomato and potato. Training our
   `potato_healthy` class on apple and tomato leaves would teach the model that
   any healthy-looking leaf is a healthy *potato* leaf — precisely the failure
   that produces a confident "no action needed" on the wrong crop.
3. **Unverified provenance.** A 2023 graduation project with no published
   annotation protocol and no inter-annotator agreement. Its reported
   mAP@50 of 0.93 is on its own test split, and its README documents no ONNX
   export, no threshold tuning, and no class-imbalance handling — so those
   numbers carry no information about field behaviour.

That third point is not a reason to dismiss it, only a reason not to inherit
its numbers. If you do want to use it, `prepare_dataset.py --annotated
<path> --remap <src=ours>` will ingest its potato classes and drop the rest.

## The real problem with PlantVillage, stated plainly

**PlantVillage is laboratory imagery.** Every image is a single detached leaf on
a uniform background under even lighting. A detector trained on it alone learns
"leaf on grey background" as much as it learns disease, and its test-split mAP —
typically 0.95+ — says almost nothing about a farmer's phone photo containing
soil, straw, shadow, several overlapping leaves and motion blur.

This is why the pipeline:

- keeps a `pv_` / `ann_` filename prefix and writes separate `data_lab.yaml` and
  `data_field.yaml` val lists,
- makes `ml/evaluate.py` report lab and field metrics **side by side** and warn
  when the gap exceeds 0.20 mAP50,
- makes `prepare_dataset.py` warn loudly when the val split contains zero
  field-condition images, saying in as many words that every metric from that
  run is a lab metric.

**Do not quote a PlantVillage-only mAP as field accuracy.** Merge field images
first.

## Class imbalance is real and measured

PlantVillage potato is roughly:

| Class | Images | Share |
|---|---|---|
| `potato_early_blight` | ~1000 | 46% |
| `potato_late_blight` | ~1000 | 46% |
| `potato_healthy` | ~152 | **7%** |

That is a **6.5 : 1** imbalance, and the minority class is the one that says
"do not spray". Left alone, the model under-predicts healthy, and the system
recommends chemicals it should not.

`prepare_dataset.py` handles this explicitly rather than hoping:

```bash
python ml/prepare_dataset.py --plantvillage <path> --out <out> \
    --cap-train 400 --oversample-min
```

- **`--cap-train`** caps majority classes in the **train split only**. val and
  test are never touched — balancing your evaluation set means measuring on a
  distribution you invented.
- **`--oversample-min`** repeats minority-class training images up to the
  majority count. Combined with per-epoch augmentation these are varied views,
  not identical copies.
- The script prints the imbalance ratio **before and after** and warns above
  1.5 : 1.

Measured on the real distribution, that turns **6.56 : 1 into 1.00 : 1**.

## Splits are stratified, not random

A random 80/10/10 over 152 healthy images can easily leave ~15 in val, and a
per-class metric off 15 images is noise. Worse, on a small dataset a random
split can put most of the hard examples in one split by chance and you will
never know.

`stratified_split()` assigns **exact per-class quotas**, deterministically by
content hash — so an image keeps its split across reruns, val scores stay
comparable, and nothing leaks from train into val. Small classes additionally
get raised to a **minimum of 20 val images** (capped at 25% of the class), so
every class is actually measurable.

## Recommended setup

```bash
# Best available: lab volume + field realism
python ml/prepare_dataset.py \
    --plantvillage /kaggle/input/plantvillage-dataset/color \
    --annotated    /kaggle/input/<your-roboflow-or-plantdoc-export> \
    --out          /kaggle/working/potato_yolo \
    --cap-train 400 --oversample-min
```

**Highest-value work you can do on this project:** photograph 200–300 real
potato leaves in Maharashtra fields — healthy and diseased, different times of
day — and annotate them in Roboflow. A few hundred genuine field images are
worth more than another ten thousand lab images, and they are what turns a
demo-grade number into a defensible one. `ml/export_feedback.py` then keeps that
set growing from expert-validated cases automatically.
