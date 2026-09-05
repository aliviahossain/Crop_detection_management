# ML pipeline

Training runs in the cloud. The laptop only ever holds code and the exported
weights. See [`DATASETS.md`](DATASETS.md) for which dataset to train on and why.

## Scope

**Potato only, three classes, 100 epochs.**

| Index | Class | Notes |
|---|---|---|
| 0 | `potato_early_blight` | *Alternaria solani* - concentric-ring lesions on lower leaves |
| 1 | `potato_late_blight` | *Phytophthora infestans* - the high-severity, weather-driven one |
| 2 | `potato_healthy` | The minority class, and the one that says "do not spray" |

The index order in `data.yaml` is authoritative and must match
`backend/app/services/taxonomy.py:CLASS_NAMES`. Swapping two lines there
silently mislabels every prediction in production, and nothing will error.

## Files

| File | Purpose |
|---|---|
| `notebooks/kaggle_train_potato_yolo.ipynb` | **Start here.** The whole pipeline end to end |
| `DATASETS.md` | Dataset comparison, imbalance analysis, provenance |
| `prepare_dataset.py` | Stratified, balanced dataset build with per-source eval lists |
| `train_yolo.py` | Training (defaults to yolov8s, 100 epochs) |
| `evaluate.py` | **Lab vs field metrics, reported separately** |
| `tune_thresholds.py` | Per-class confidence thresholds from an asymmetric cost model |
| `benchmark_inference.py` | Measured CPU latency, for the model-size decision |
| `export_onnx.py` | Export + verify the output shape the backend expects |
| `export_feedback.py` | Package expert-validated field cases for the next training run |
| `train_risk_xgb.py` | Optional secondary risk layer - needs real outbreak data |
| `weights/` | Drop `best.onnx`, `thresholds.json` here; gitignored |

## Full run

```bash
# 1. Build the dataset - stratified splits, balanced train, per-source val lists
python ml/prepare_dataset.py \
    --plantvillage /kaggle/input/plantvillage-dataset/color \
    --annotated    /kaggle/input/<field-dataset> \
    --out          /kaggle/working/potato_yolo \
    --cap-train 400 --oversample-min

# 2. Train
python ml/train_yolo.py --data /kaggle/working/potato_yolo/data.yaml --epochs 100

# 3. Evaluate honestly - lab and field side by side
python ml/evaluate.py --weights ml/weights/best.pt --data /kaggle/working/potato_yolo/data.yaml

# 4. Tune per-class thresholds
python ml/tune_thresholds.py --weights ml/weights/best.pt --data /kaggle/working/potato_yolo/data.yaml

# 5. Export and verify ONNX
python ml/export_onnx.py --weights ml/weights/best.pt

# 6. Measure inference latency on the deployment hardware
python ml/benchmark_inference.py --model ml/weights/best.onnx
```

Then download `ml/weights/` and place it in the repo. The backend picks it up on
the next request.

## Design decisions

### Model size: `yolov8s`, not `yolov8n`

Nano is the least accurate variant in the family. Accuracy is what matters when
a wrong answer means the wrong pesticide, so `s` is the default: roughly triple
the parameters (11.2M vs 3.2M) for a real mAP gain, and still inside the CPU
latency budget.

Do not take "still fast enough" on trust - `benchmark_inference.py` measures it
on your hardware and warns if p95 exceeds 1000 ms. Train `n` as well if you want
the offline story: ship `s` on the server, `n` in a phone build, and compare
them directly:

```bash
python ml/benchmark_inference.py --model s.onnx --model n.onnx
```

### Augmentation: geometry freely, colour barely

`hsv_h=0.010`, `hsv_s=0.5`, `hsv_v=0.3`, `degrees=15`, `translate=0.10`,
`scale=0.40`, `fliplr=0.5`, `flipud=0.0`, `mosaic=1.0`, `close_mosaic=10`.

Lesion **colour** is the diagnostic signal separating early from late blight.
Aggressive hue jitter teaches the model to ignore exactly the feature that
matters. `flipud=0` because leaves are photographed the right way up.
`close_mosaic=10` runs the final epochs without mosaic so validation resembles
real single-image inference.

This matters more than usual because the dataset is small - augmentation is
doing real regularisation work, but the *wrong* augmentation on a small dataset
destroys the signal faster than it regularises.

### Splits: stratified with exact quotas, deterministic

Random splitting a 152-image class can leave ~15 in val, where a per-class
metric is noise; on a small dataset it can also concentrate the hard examples in
one split by chance. `stratified_split()` assigns exact per-class quotas ordered
by content hash, so splits are reproducible across reruns and nothing leaks
train→val. Small classes are raised to a minimum of 20 val images, capped at 25%
of the class.

### Class balance: measured, capped, oversampled

PlantVillage potato is ~6.5:1 imbalanced against `healthy`. `--cap-train` caps
majority classes in the **train split only** (balancing val/test would mean
measuring on an invented distribution), `--oversample-min` repeats the minority
up to the majority count, and the script prints the ratio before and after,
warning above 1.5:1. Measured: **6.56:1 → 1.00:1**.

### Thresholds: tuned against an asymmetric cost

The stock `conf=0.25` assumes a false positive and a false negative cost the
same. Here they do not:

| Class | Objective | Reason |
|---|---|---|
| `potato_early_blight` | F2 (recall) | Catch it; triage filters the uncertain ones |
| `potato_late_blight` | F2 (recall) | Fast-moving - a miss costs the field |
| `potato_healthy` | F0.5 (precision) | Only say "healthy" when sure |

`tune_thresholds.py` runs one inference pass at conf 0.001, then sweeps offline
and writes `weights/thresholds.json`. The backend loads it automatically and
reports it at `GET /detect/status`; absent, it falls back to the single env
threshold and says so.

### Evaluation: lab and field are never merged into one number

`evaluate.py` reports `data_lab.yaml` and `data_field.yaml` side by side and
warns when the gap exceeds 0.20 mAP50. With no field split it refuses to present
a headline figure as field accuracy. See [`DATASETS.md`](DATASETS.md).

## Secondary risk layer

`train_risk_xgb.py` exists but ships no model, on purpose. It needs historical
rows linking weather and field context to confirmed outbreaks - CROPSAP
Maharashtra bulletins, ICAR/NCIPM records, or this system's own confirmed cases
once enough exist. It refuses to train below 200 rows and refuses to save a
model below 0.6 AUC, because a model fitted on 30 rows would look like machine
learning and behave like noise.
