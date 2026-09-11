# croprow_disease — two-class crop-row plant health

Real-time detection of **where crop plants are and whether they look healthy**
for a cultivator-mounted camera: two classes, detection boxes, video inference
with persistent track IDs and a per-plant health verdict.

| class | id | what it means |
| --- | --- | --- |
| `healthy` | 0 | green, vigorous canopy |
| `unhealthy` | 1 | brown, yellowed, or otherwise off-colour |

Parallel to — and independent of — the single-class [`../croprow/`](../croprow/)
localizer and the potato disease stack in [`../ml/`](../ml/). Nothing here
imports from or modifies either.

- **Two classes only.** No weed classes, no per-disease breakdown.
- **Real data only.** No synthetic or AI-generated training images.
- **Public vs own data are never merged.** Reported as separate rows/tables.
- **Class order is fixed.** `0 = healthy, 1 = unhealthy`. Ultralytics matches
  classes by index, so a dataset labelled the other way round trains happily and
  inverts every prediction. Both dataset paths check this and refuse.

---

## Two ways to get data in

Both write the **same** `data/health.yaml`, so notebooks 03–08 work unchanged
and do not know which produced it.

### A. A provided healthy/unhealthy dataset → `01b_provided_dataset` ← the main path

Point `DATASET_ROOT` (or `HEALTH_DATASET`) at the dataset and run the notebook.
Three layouts are accepted:

| layout | looks like | what happens |
| --- | --- | --- |
| `yaml` | a `data.yaml` / `dataset.yaml` at the root | validated and adopted, split taken from it |
| `split` | `images/train` + `images/val`, mirrored `labels/` | adopted as-is (`valid` / `test` also recognised — Roboflow uses `valid`) |
| `flat` | `images/` + `labels/`, no split | split generated, **grouped** so one clip's frames stay on one side |

Images are never copied or modified. Before writing anything it checks class
names **and order**, scans every label file, and refuses a dataset with missing
labels, out-of-range class ids, or an empty class — each of which trains a
quietly broken model rather than failing.

### B. Bootstrap from LettuceMOTS → `01_dataset_prep`

[LettuceMOTS](https://drive.google.com/drive/folders/1HIoiyUOu4zYh8jHgqebnbZF_Ewn6Hq62)
is single-class ("a lettuce plant") with no health attribute, so the class is
**derived from the real pixels inside each real annotation polygon**:

| what | from | how |
| --- | --- | --- |
| box | the human-drawn polygon | min/max of its normalized vertices — same as `croprow/` |
| class | the pixels it encloses | the colour rule in `health.py` |

**These are auto-labels, not agronomist ground truth.** Nothing is synthetic —
every pixel is a real frame, every polygon a real annotation — but a heuristic
decided healthy vs unhealthy, so any metric against them measures agreement with
that rule. Say so wherever you quote one.

> **LettuceMOTS contains no unhealthy plants** — 7,844 healthy and **0**
> unhealthy across all 596 labeled frames. Path B is therefore a *localisation
> bootstrap* only: useful weights to fine-tune from, not a two-class model. See
> [`RESULTS.md`](RESULTS.md) for the measurement and how it was established.

---

## The colour rule (`health.py`)

For each pixel inside a polygon, three tests decide whether it is vigorous green
canopy:

1. **Hue** in the green band (OpenCV H 35–85). Senescent tissue falls below it.
2. **Excess Green index** `ExG = 2g − r − b` on chromatic coordinates — the
   standard RGB vegetation index, illumination-normalised, so it survives a
   tractor camera moving in and out of its own shadow.
3. **Saturation / value floors**, dropping grey soil and black shadow out of the
   denominator instead of letting them vote.

`health_score` is the fraction of non-background polygon pixels that pass;
≥ `green_frac_threshold` → healthy.

### The quality gate, and why it exists

Run without it on LettuceMOTS, the rule returned an "unhealthy" tail of ~1%.
Rendering those crops showed **motion blur, shadow and defocus — not brown
plants**. The populations separate on image quality, not colour:

| metric | healthy p25 / median | "unhealthy" p75 / max |
| --- | --- | --- |
| sharpness (var. of Laplacian) | 2255 / 3126 | 107 / 899 |
| mean HSV value | 146 / 158 | 107 / 114 |

`min_sharpness` / `min_mean_value` sit in those gaps. Instances too blurred,
dark or small to judge default to `healthy` and are counted as **low-confidence**
(11.9% of LettuceMOTS) — a colour rule with nothing trustworthy to look at must
not be the thing that invents a disease detection. A genuinely brown plant shot
sharply still passes the gate and is still classified on colour.

**Do this check on your own data too** — notebook `02_verify_labels` renders the
lowest/median/highest-scoring crops precisely so you can see what the rule is
reacting to before trusting a single number.

All thresholds live in `HealthParams` and are set from each notebook's config
cell; never edit the module to retune.

---

## Environment

This module **shares the croprow environment** — it needs no venv of its own.

| env | Python | for |
| --- | --- | --- |
| `croprow/.venv` | 3.11 | `croprow/` **and** `croprow_disease/` |
| `../.venv` | 3.13 | the potato backend — **leave untouched** |

```bash
py -3.11 -m venv croprow/.venv
croprow/.venv/Scripts/activate            # Windows
pip install -r croprow_disease/requirements-train.txt
python -m ipykernel install --user --name croprow --display-name "Python 3 (croprow)"
```

Notebooks 01 / 01b / 02 need only numpy, opencv, matplotlib, pyyaml and jupyter;
03–08 add torch + ultralytics (install the torch build matching your CUDA from
pytorch.org). A GPU is strongly recommended for training.

---

## Notebooks (`croprow_disease/notebooks/`)

| # | notebook | status | what it does |
| --- | --- | --- | --- |
| 01 | `01_dataset_prep` | **run** | LettuceMOTS bootstrap: verify labels, split by sequence, derive boxes + colour classes, emit `data/health.yaml` (nc=2) |
| 01b | `01b_provided_dataset` | ready | **the main path** — validate a provided healthy/unhealthy dataset, emit the same yaml |
| 02 | `02_verify_labels` | ready | draw class-coloured boxes; score histogram; diagnostic strip showing what the rule reacts to |
| 03 | `03_train` | ready | train YOLO11n (nc=2); **refuses to start** on a single-class split |
| 04 | `04_finetune` | unrun | low-LR fine-tune on **your own** 2-class frames (set `OWN_DATA_YAML`) |
| 05 | `05_evaluate` | ready | per-class metrics, LettuceMOTS and own-frames in **separate tables** |
| 06 | `06_detect_video` | ready | detect + ByteTrack IDs + live FPS + **per-plant health rollup** → annotated mp4 |
| 07 | `07_speed` | ready | ONNX + TensorRT FP16 export; benchmark imgsz 640/512/416 |
| 08 | `08_package_dataset` | ready | build a portable, drop-in 2-class YOLO bundle for a trainer |

01 is already executed. The rest ship **unrun** — whoever trains runs them; they
stop with a clear message if weights or frames are missing rather than
fabricating a fallback.

### Per-plant rollup (06)

Because ByteTrack IDs persist, per-frame counts roll up into one verdict per
plant: a track is flagged when at least `TRACK_UNHEALTHY_FRAC` of its sighted
frames were unhealthy. That is the number worth acting on — a single frame's
count flickers with occlusion and blur.

---

## Where the data lives

Datasets live **outside** this repo and are never committed. Point at them with:

| env var | used by | default |
| --- | --- | --- |
| `LETTUCE_ROOT` | 01, 02, 08 | `D:\croprow_dataset\LettuceMOTS` |
| `HEALTH_DATASET` | 01b | `D:\croprow_dataset\crop_health` |
| `OWN_DATA_YAML` | 04, 05 | unset (own-frames eval is skipped) |

Derived LettuceMOTS labels are written to `<LETTUCE_ROOT>/train/labels_health/`
— deliberately **not** `train/labels/`, which `croprow/` uses for its
single-class labels over the same frames. Ultralytics finds labels by swapping
`images` → `labels` in the image path, so sharing that directory would mean
whichever module ran last silently decided what the other one trained on.

Tracked in git: the notebooks, `health.py`, `utils.py`, `dataset.py`, the data
yaml, the train/val split lists and `RESULTS.md`. Not tracked: frames, videos,
run outputs, weights.

---

## Speed target

**≥ 30 FPS end-to-end.** FPS in 06/07 is measured with a real timer around the
**full** loop — frame read + inference + tracking + draw — not the model call
alone. 07 flags any config that misses the target honestly.

## Results

Every run appends a row to [`RESULTS.md`](RESULTS.md): mAP50, mAP50-95,
precision, recall, **per-class mAP50**, epochs, imgsz, which dataset, and where
the labels came from. Read the `mAP50 unhealthy` column first — with imbalanced
classes a strong mean can hide a class the model never predicts.

## Serving note

`export_onnx.py` writes `models/best.onnx`. This model has **two** classes, so a
consumer decoding the raw ONNX output reads 6 values per prediction (4 box + 2
class scores) and takes the argmax of the two class scores — not the 5-value,
single-objectness layout of the `croprow/` model. A serving path written against
that one will not error here; it will just be wrong.
