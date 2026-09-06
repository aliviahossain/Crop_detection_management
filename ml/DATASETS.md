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

---

## What was actually trained

Two sequential runs. Both are documented here exactly as they ran.

### Run 1 — Base training (PlantVillage only)

**Dataset:** PlantVillage potato — ~2,150 images, lab only.  
**Flags:** `--cap-train 400 --oversample-min --clean`  
**Epochs:** 68/100 (early stopping, patience=25)  
**Result:** mAP50=0.995 — LAB METRIC ONLY. Do not quote as field accuracy.

### Run 2 — Fine-tuning (PlantVillage + cropguard-field-potato)

**Dataset:** PlantVillage (1,200 capped/oversampled) + 343 field images  
**Starting weights:** `best.pt` from Run 1  
**Flags:** `--lr0 0.001 --epochs 50`  
**Result:** Combined mAP50=0.928 (lab + field mixed val). Lab split retained at 0.995
confirming no catastrophic forgetting.

---

## The decision: PlantVillage + cropguard-field-potato

PlantVillage supplies volume. The field dataset supplies realism. Neither alone
is sufficient, for opposite reasons. PlantVillage scores near-perfectly on its
own test split and then degrades on a real phone photo, because what it actually
learned is "leaf on grey". The field dataset supplies genuine field-condition
images — cluttered backgrounds, multiple overlapping leaves, varying lighting —
which is what the farmer's camera will actually send.

### The field dataset: cropguard-field-potato

**Source:** Roboflow Universe — `absolute-foods-ownqh/potato-disease-cw1hc`  
**License:** CC BY 4.0  
**Original classes:** EarlyBlight(0), Healthy(1), LateBlight(2), YVirus(3)  
**Original scope:** Mixed crops — potato, tomato, eggplant, bean, watermelon, apple

**What was done to it before training:**

1. Filtered to potato-only images by filename — non-potato images and labels
   deleted.
2. Class indices remapped to match taxonomy.py:CLASS_NAMES:
   - `0` (EarlyBlight) → `0` ✓ unchanged
   - `1` (Healthy) → `2`
   - `2` (LateBlight) → `1`
   - `3` (YVirus) → dropped entirely
3. Septoria-labeled images dropped — Septoria (*Septoria* spp.) is not late
   blight (*Phytophthora infestans*). Different pathogen, different treatment.
   Merging them would bake a misclassification into the training data.
4. Images with only YVirus annotations dropped (empty label file after step 2).
5. Roboflow-baked augmentation accepted as-is (3x output including vertical
   flips). This is documented noise — a small contamination in a minority dataset
   during fine-tuning from a strong base model.

**Final usable pairs after cleaning:** 343 images/labels  
**Approximate class breakdown:** ~229 early blight, ~110 late blight, healthy
appears only as background annotations within disease images — no standalone
healthy field images exist.

**Flattened and re-split** 80/10/10 by `merge_field.py` (seed=42) rather than
using Roboflow's original splits — Roboflow's splits had no knowledge of the
PlantVillage distribution and would have put augmented copies on both sides of
the train/val boundary.

### What the merge does and does not fix

| | Early blight | Late blight | Healthy |
|---|---|---|---|
| PlantVillage | ~1,000 | ~1,000 | **152** |
| cropguard-field-potato | ~229 | ~110 | ~0 standalone |
| **Combined** | ~1,229 | ~1,110 | **~152** |

The disease class imbalance is essentially resolved (1.1:1 after merge).
**The healthy class is unchanged.** No field standalone healthy images were
found — healthy leaves appear only as background annotations within disease
images. This is the weak point of the current dataset. `--cap-train` and
`--oversample-min` equalise the training split, but healthy ends up roughly
two-thirds duplicated images. The run prints that percentage rather than hiding
it behind the parity claim.

**The honest position: healthy is the weak class, and no flag fixes that.** The
real remedy is standalone healthy potato field photographs, which the expert
review queue is designed to accumulate (`ml/export_feedback.py`).

---

## Options compared

| | **PlantVillage** | **cropguard-field-potato** | **PlantDoc** | **Roboflow "Plant Diseases Detection"** |
|---|---|---|---|---|
| Potato images | ~2,150 | 343 (cleaned) | low hundreds | ~300 potato after filtering |
| Potato classes | Early, Late, **Healthy** | Early, Late, Healthy (background only) | Early, Late, Healthy | Early, Late — **no potato-specific healthy** |
| Conditions | Lab: one leaf, uniform grey | **Real field conditions** | **Real field conditions** | Mixed |
| Task type | Classification (no boxes) | Detection (real boxes) | Detection (real boxes) | Detection (real boxes) |
| Provenance | ICAR/Penn State, peer-reviewed | Roboflow CC BY 4.0, 2023 | Published paper (Singh et al., CoDS-COMAD 2020) | Unverified 2023 student project |
| Role here | **Volume base** | **Field realism — used in Run 2** | Future option — not yet used | Reference for pipeline structure only |

### PlantDoc — why it was not used in Run 2

PlantDoc is the stronger academic option: published paper, real bounding boxes,
genuine field conditions. It was not used in Run 2 because the Roboflow field
dataset was already cleaned, remapped, and available at training time. PlantDoc
should be the next dataset to integrate — it adds annotated field images with
documented provenance that the Roboflow dataset lacks.

To integrate:
```bash
python ml/prepare_dataset.py \
    --plantvillage /kaggle/input/plantvillage-dataset/color \
    --annotated    /kaggle/input/plantdoc-potato \
    --out          /kaggle/working/datasets/potato_yolo \
    --cap-train 400 --oversample-min
```
Then run `merge_field.py` to add cropguard-field-potato on top.

### Why PlantVillage is the base and not the Roboflow set

1. **Volume.** ~2,600 images spread over 10 classes. Filtering to potato leaves
   a few hundred images across two classes — against PlantVillage's ~2,000 for
   the same two classes.
2. **No potato healthy class.** Its healthy category spans apple, corn, tomato,
   and potato. Training `potato_healthy` on apple and tomato leaves teaches the
   model that any healthy-looking leaf is a healthy potato leaf — the failure
   that produces a confident "no action needed" on the wrong crop.
3. **Unverified provenance.** A 2023 graduation project with no published
   annotation protocol and no inter-annotator agreement.

---

## The real problem with PlantVillage, stated plainly

**PlantVillage is laboratory imagery.** Every image is a single detached leaf on
a uniform background under even lighting. A detector trained on it alone learns
"leaf on grey background" as much as it learns disease, and its test-split
mAP — typically 0.95+ — says almost nothing about a farmer's phone photo
containing soil, straw, shadow, several overlapping leaves, and motion blur.

This is why the pipeline:

- keeps a `pv_` / `ann_` filename prefix and writes separate `data_lab.yaml`
  and `data_field.yaml` val lists,
- makes `ml/evaluate.py` report lab and field metrics **side by side** and warn
  when the gap exceeds 0.20 mAP50,
- makes `prepare_dataset.py` warn loudly when the val split contains zero
  field-condition images, saying in as many words that every metric from that
  run is a lab metric.

**Do not quote a PlantVillage-only mAP as field accuracy.**

---

## Class imbalance is real and measured

PlantVillage potato distribution:

| Class | Images | Share |
|---|---|---|
| `potato_early_blight` | ~1000 | 46% |
| `potato_late_blight` | ~1000 | 46% |
| `potato_healthy` | ~152 | **7%** |

That is a **6.5:1** imbalance, and the minority class is the one that says
"do not spray". Left alone, the model under-predicts healthy, and the system
recommends chemicals it should not.

`prepare_dataset.py` handles this explicitly:

```bash
python ml/prepare_dataset.py --plantvillage <path> --out <out> \
    --cap-train 400 --oversample-min
```

- **`--cap-train`** caps majority classes in the **train split only**. Val and
  test are never touched — balancing your evaluation set means measuring on a
  distribution you invented.
- **`--oversample-min`** repeats minority-class training images up to the
  majority count.
- The script prints the imbalance ratio **before and after** and warns above
  1.5:1.

Measured on the real distribution: **6.56:1 → 1.00:1**.

---

## Splits are stratified, not random

A random 80/10/10 over 152 healthy images can easily leave ~15 in val, and a
per-class metric off 15 images is noise. `stratified_split()` assigns **exact
per-class quotas**, deterministically by content hash — so an image keeps its
split across reruns, val scores stay comparable, and nothing leaks from train
into val. Small classes additionally get raised to a **minimum of 20 val
images** (capped at 25% of the class).

---

## What is still missing

**Standalone healthy field images.** This is the single highest-value thing
that can be done for the model right now. Healthy appears only as background
annotations in disease images. The model's healthy class detection in field
conditions relies entirely on PlantVillage lab images. A farmer photographing
a fully healthy plant in a real field is asking the model to generalise from
grey-background images to soil-and-shadow backgrounds — a gap that exists and
is currently unmeasured.

**Dedicated field val split.** The current combined val (254 images) includes
34 field images — too small for a standalone field metric. The pipeline is
built to support it (`data_field.yaml`) but there is not yet enough field data
to populate it meaningfully.

---

## Recommended next dataset increment

```bash
# Integrate PlantDoc for documented field-condition annotations
python ml/prepare_dataset.py \
    --plantvillage /kaggle/input/plantvillage-dataset/color \
    --annotated    /kaggle/input/plantdoc-potato \
    --out          /kaggle/working/datasets/potato_yolo \
    --cap-train 400 --oversample-min

# Then add the existing field dataset on top
python ml/merge_field.py \
    --field-dir /kaggle/input/cropguard-field-potato/field_flat \
    --out       /kaggle/working/datasets/potato_yolo \
    --seed 42 --ratios 0.8 0.1 0.1
```

**Highest-value work:** photograph 200–300 real potato leaves in Maharashtra
fields — healthy and diseased, different times of day — and annotate in
Roboflow. A few hundred genuine field images are worth more than another ten
thousand lab images. `ml/export_feedback.py` keeps that set growing from
expert-validated cases automatically.