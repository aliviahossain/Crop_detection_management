# CropGuard Maharashtra

**SIH 2026 · PS26131 — Crop Disease & Pest Detection System**
Government of Maharashtra (Maharashtra State Innovation Society)

A farmer- and extension-worker-facing crop health system for **potato**: photo-based
disease detection, weather-driven risk forecasting *before* symptoms appear, IPDM
advisories in Marathi/Hindi/Bengali/English, geospatial hotspot mapping, an expert validation
queue that feeds retraining, and a dashboard for agriculture officials.

---

## Scope, stated plainly

**The deployed detector covers potato only, with three classes:**
`potato_early_blight`, `potato_late_blight`, `potato_healthy`.

That is a deliberate choice, not a shortcut:

- Late blight is the textbook weather-driven epidemic — the **Smith Period** risk model
  is defined for it, so the detection and forecasting halves of this system reinforce
  each other on the same crop.
- Potato is a major Maharashtra rabi crop with real extension demand.
- Clean training imagery exists (PlantVillage), so the model can actually be trained on
  a free Kaggle GPU in one session.

Adding a crop is a dataset-and-retrain task: extend `ml/data.yaml`,
`backend/app/services/taxonomy.py`, and the knowledge base. No architectural change.

## Honesty about what is real

The system reports its own degraded components at `GET /meta/health`, and the UI shows a
banner. On a fresh clone, with no weights and no API keys:

| Component | Fresh clone behaviour |
|---|---|
| Image detection | **Unavailable** — cases are routed to the expert queue rather than given a guessed diagnosis. |
| Weather | Deterministic **synthetic feed**, flagged `synthetic: true` in every response. |
| Risk models | **Fully working** — the agronomic models need no training data. |
| Advisory / RAG | **Fully working** — BM25 retrieval if ChromaDB is not installed. |
| Marathi / Hindi / Bengali | **Fully working** — template catalog, no API key needed. |
| XGBoost risk layer | **Inactive by design** — no historical outbreak data exists yet to train it honestly. |

Nothing fabricates a result to look complete.

`GET /meta/health` reports two separate lists, because conflating them misleads in both
directions:

- **`degraded`** — something that should work and does not. Only these raise a banner.
- **`by_design`** — a documented, deliberate state. Template-only advisories and an
  untrained XGBoost layer are the specification, not faults.

---

## Quick start

Requires Python 3.10–3.13 and Node 18+.

```bash
# 1. Backend
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -r backend/requirements.txt
cp .env.example .env              # optional: add OPENWEATHER_API_KEY

uvicorn app.main:app --reload --app-dir backend
# API docs: http://localhost:8000/docs
# Health:   http://localhost:8000/meta/health

# 2. Demo data (so the map and dashboard have something to show)
python scripts/seed_demo_data.py --cases 120

# 3. Frontend
cd frontend && npm install && npm run dev
# http://localhost:5173
```

Tests:

```bash
pip install -r backend/requirements-dev.txt
pytest backend/tests -q      # 96 tests, no network, no trained model needed
```

Optional extras. Each has a tested fallback, so none is required — but installing them
upgrades retrieval from BM25 to ChromaDB vector search and enables the XGBoost layer:

```bash
pip install -r backend/requirements-extras.txt   # ChromaDB, LangGraph, XGBoost, SHAP
pip install -r backend/requirements-train.txt    # ultralytics + torch (training only)
```

### Real weather (the one thing that needs your own key)

Without a key the risk engine runs on a deterministic **synthetic** feed, flagged
`synthetic: true` in every response. To use real observations, get a free key at
[openweathermap.org/api](https://openweathermap.org/api) and set it in `.env`:

```bash
OPENWEATHER_API_KEY=your_key_here
```

The free tier covers current conditions and a 5-day forecast, which is what the agronomic
models need. It has no history API — so past hours come from the system's own
`weather_observations` cache, which fills up as it runs, and any remaining gap is
synthetic backfill that the response reports explicitly.

---

## Architecture

```
┌──────────────────────────────┐
│  React frontend (Vite)       │  farmer flow + officer dashboard + Leaflet map
└──────────────┬───────────────┘
               │ REST (/api proxied in dev)
┌──────────────▼───────────────┐
│  FastAPI backend             │
├──────────────────────────────┤
│ POST /detect     │ YOLOv8s via ONNX Runtime (CPU) → class + confidence + bbox
│ POST /risk       │ Smith / Beaumont / TOMCAST / degree-days + OpenWeatherMap
│ POST /advisory   │ LangGraph pipeline over a human-reviewed IPDM knowledge base
│ GET  /hotspots   │ Geo-grid aggregation, confirmed cases weighted above unverified
│ POST /sensors    │ Pest-trap & field-sensor ingestion
│ GET  /review     │ Expert validation queue → training samples
│ /followups       │ Did the treatment work? Failure escalates to a laboratory
│ /dashboard       │ Aggregates for agriculture officials
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│  SQLite / Postgres           │  cases · follow-ups · sensor readings ·
└──────────────────────────────┘  training samples · weather cache
```

### The core loop

Both entry points converge in `backend/app/services/pipeline.py`, so a photo-triggered
case and a proactive weather alert get the same safety gate and the same advisory
pipeline:

```
image?  → detection ─┐
                     ├→ risk assessment → TRIAGE → advisory (RAG) → case + follow-up
location → weather ──┘                      │
                                            └→ escalate to expert instead of recommending
                                               a pesticide, when confidence is low, signals
                                               conflict, or a treatment has already failed
```

---

## Design decisions worth knowing

### 1. Risk forecasting is rule-based first, ML second

There is no ready-made labelled dataset linking weather + crop stage + variety + soil +
local pest history to actual outbreak events for Indian crops. So the **primary layer is
published agronomic models** that run deterministically today:

| Model | Target | Criterion |
|---|---|---|
| **Smith Period** (Smith, 1956) | Late blight | 2 consecutive days: min temp ≥ 10 °C **and** ≥ 11 h at RH ≥ 90% |
| **Beaumont Period** (1947) | Late blight | 46 consecutive hours ≥ 10 °C and RH ≥ 75% (earlier, looser warning) |
| **TOMCAST DSV** | Early blight | Daily severity 0–4 from leaf-wetness hours × mean temperature; spray at 15 DSV |
| **Degree-days** | Tuber moth, aphids | Single-triangle accumulation; ~360 DD above 10 °C per tuber-moth generation |

These are then adjusted by **crop stage × variety susceptibility × soil drainage**, plus
confirmed nearby cases and live trap counts.

The **XGBoost + SHAP secondary layer** (`ml/train_risk_xgb.py`) is additive refinement.
It refuses to train on fewer than 200 rows and refuses to save a model scoring below 0.6
AUC, and it can never move the rule-based score by more than ±0.20 — a thinly-trained
model must not be able to override a fired Smith Period.

The dataset it needs is a by-product of running the system: once expert-confirmed cases
accumulate, `scripts/export_risk_dataset.py` builds the training CSV from them (features
from the weather *before* each case, label from confirmed outbreaks *after* it). It
refuses to export seeded demo rows or synthetic-weather rows unless explicitly forced, so
the layer activates on real evidence or not at all.

### 2. Every advisory is traceable and safety-gated

Doses are **parsed from reviewed markdown tables**, never generated. Each advisory
returns the knowledge-base sections it drew from. The triage layer withholds the dose
table entirely when confidence is low, when the image and weather disagree, or when two
follow-ups have already reported a treatment failing (which suggests fungicide
resistance, not a bigger dose).

### 3. Marathi, Hindi and Bengali work without an API key

Advisories are assembled from a **translated message catalog**
(`backend/app/services/translate.py`) — 49 messages × 4 languages — so a farmer gets
genuinely native-language guidance with no network, no LLM, and no per-request cost. An
LLM is used only to translate free-text knowledge-base excerpts, and falls back to English
rather than risk a mistranslated dose.

The catalog is checked structurally by `backend/tests/test_translations.py`: right script
per language, placeholders preserved, no entry carrying another entry's text, and no
language silently below 100% coverage. That suite exists because a scripted edit once
spliced Bengali into the wrong entry and every other test still passed.

### 4. Hotspots weight expert-confirmed cases above model output

An officer should not deploy staff on unverified AI predictions, but should still see a
spike of pending reports. Confirmed cases count 1.0, unreviewed predictions count 0.4,
and both are reported separately.

### 5. ONNX on CPU is the serving path

No torch on the dev laptop, a few hundred ms per image, and the same artifact an
offline on-device build would ship. The export is shape-verified, the decoder is tested
against a real onnxruntime session, and `ml/benchmark_inference.py` measures the latency
rather than asserting it.

### 6. Detection thresholds encode an asymmetric cost

A single `conf=0.25` assumes a false positive and a false negative cost the same. Missing
late blight can cost the field; a false positive costs a spray and is *already* caught by
the triage layer, which withholds the dose table below the low-confidence threshold. So
disease classes are tuned for recall and `healthy` for precision, per class — see
`ml/tune_thresholds.py`.

---

## Training the model

**Never train locally** — the dev machine has 16 GB RAM and very little C: space, and
training belongs on a GPU. Only the exported weights (a few MB) come back down.

Open `ml/notebooks/kaggle_train_potato_yolo.ipynb` on **Kaggle** (GPU T4 ×2, internet on),
add the `abdallahalidev/plantvillage-dataset` input, and run it through. Kaggle rather than
Colab: Colab reclaims GPUs from idle sessions and would kill a 100-epoch run with no
checkpoint, while Kaggle gives a 30 hr/week quota and a 12 hr session limit.

Equivalent CLI:

```bash
python ml/prepare_dataset.py --plantvillage <path> --annotated <field-data> \
    --out datasets/potato_yolo --cap-train 400 --oversample-min
python ml/train_yolo.py       --data datasets/potato_yolo/data.yaml --epochs 100
python ml/evaluate.py         --weights ml/weights/best.pt --data datasets/potato_yolo/data.yaml
python ml/tune_thresholds.py  --weights ml/weights/best.pt --data datasets/potato_yolo/data.yaml
python ml/export_onnx.py      --weights ml/weights/best.pt
python ml/benchmark_inference.py --model ml/weights/best.onnx
```

Then place `ml/weights/` in the repo — `GET /meta/health` stops reporting
`detection_model_missing`, and `GET /detect/status` shows the tuned thresholds in use.

### What this pipeline does that a stock YOLO tutorial does not

| Concern | How it is handled |
|---|---|
| **Class imbalance** | PlantVillage potato is ~6.5:1 against `healthy` — the class that says *do not spray*. `--cap-train` caps majority classes in the train split only; `--oversample-min` lifts the minority. Measured **6.56:1 → 1.00:1**, printed before and after. |
| **Split stratification** | Exact per-class quotas assigned by content hash: reproducible across reruns, no train/val leakage, and small classes are raised to ≥20 val images so their metric is a measurement rather than noise. |
| **Model size** | `yolov8s` by default, not nano. Nano is the least accurate variant, and accuracy matters when a wrong answer means the wrong pesticide. `benchmark_inference.py` measures whether it fits the latency budget rather than assuming it. |
| **Augmentation** | Geometry augmented freely, colour barely (`hsv_h=0.010`, `flipud=0`). Lesion colour is the signal separating early from late blight; hue jitter would teach the model to ignore it. |
| **Confidence thresholds** | Tuned per class against an asymmetric cost: F2 (recall-weighted) for the diseases because a missed blight costs the field, F0.5 (precision-weighted) for `healthy` because a false "healthy" is how delayed treatment happens. |
| **Honest metrics** | `evaluate.py` reports **lab and field mAP separately** and warns when the gap exceeds 0.20 mAP50. |
| **ONNX** | Export is verified (output shape and `nc == 3`), and the serving decoder is tested against a real onnxruntime session. |

> **The caveat that matters most.** PlantVillage is *laboratory* imagery: one leaf on a
> uniform grey background. A model trained on it alone learns the background as much as the
> disease, scores ~0.95+ on its own test split, and degrades on a real phone photo. The
> pipeline warns loudly when your val split contains zero field images, and `evaluate.py`
> refuses to present a lab number as field accuracy. **Merge field-condition images before
> quoting any figure** — see [`ml/DATASETS.md`](ml/DATASETS.md).

### The feedback loop

Expert decisions in `/review` write `TrainingSample` rows.
`python ml/export_feedback.py --out datasets/feedback_01` packages them for the next
training run, and warns when a batch is too small or dominated by one district. It is
deliberately a manual step — retraining on unexamined field data is how a model quietly
degrades.

---

## Repository layout

```
backend/app/
  routers/       detect · risk · advisory · hotspots · sensors · review · followup · dashboard · meta
  services/      detector · weather · risk_models · risk_engine · risk_secondary
                 knowledge_base · advisory · triage · translate · pipeline · geo · taxonomy
  data/kb/       IPDM knowledge base (human-reviewed markdown — edit this, not the code)
  models.py      cases · follow-ups · sensor readings · training samples · weather cache
backend/tests/   96 tests: agronomic models, triage rules, ONNX decoding (fake and
                 real onnxruntime session), per-class thresholds, translation
                 integrity across 4 languages, full API
ml/              dataset prep · training · evaluation · threshold tuning · benchmarking
                 ONNX export · feedback export · risk XGBoost
ml/DATASETS.md   dataset comparison, imbalance analysis, provenance
ml/notebooks/    Kaggle training notebook (potato, 3 classes, 100 epochs)
frontend/src/    React app — farmer flow, risk page, Leaflet map, dashboard, review queue
scripts/         demo data seeding · risk-dataset export for the XGBoost layer
docs/            architecture notes and PS traceability matrix
```

## Knowledge base

`backend/app/data/kb/*.md` holds the IPDM content: symptoms, dose tables, cultural
practice, safe-use rules, referral criteria. It is markdown with YAML front matter so an
agronomist can review and correct it in a pull request without touching code.

**Every dose carries `review_status: needs_local_validation`.** The figures are the
commonly published ICAR/CPRI extension rates, but they must be checked against the CIB&RC
product label and the local KVK before this system is used by a real farmer. After
editing, run `POST /advisory/reindex`.

## Configuration

See `.env.example`. Everything runs without any key; keys upgrade components from their
documented fallbacks to live data.

---

## Traceability to the problem statement

See [`docs/PS_TRACEABILITY.md`](docs/PS_TRACEABILITY.md) — every required capability in
the official "Expected Solution" text mapped to the code that implements it.
