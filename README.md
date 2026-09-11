# CropGuard Maharashtra

**Smart India Hackathon 2026 · Problem Statement PS26131 — Early detection and management of crop diseases and pest infections**
Government of Maharashtra · Maharashtra State Innovation Society (Dept. of Skills, Employment, Entrepreneurship and Innovation)

| | |
|---|---|
| **Problem Statement ID** | 26131 |
| **Theme** | Agriculture, Food-Tech & Rural Development |
| **Category** | Software |
| **Team ID** | SIH2613/0149 |
| **Team name** | git blame |

**Team members** — Om Singh Lodhi · Alivia Hossain · Aditi Bande · Karuna Anjana · Gaurav Vaishampayan · Pradyumna Verma

**Repository:** https://github.com/aliviahossain/Crop_detection_management
**Deployed application:** https://cropguard-frontend-rhzv.onrender.com/
**Reference repository (crop-row lab):** https://github.com/NanH5837/LettuceMOTS

---

CropGuard is a proactive, offline-capable crop-health platform for farmers and agricultural
officers, focused on **potato**, with an in-development research lab for autonomous field
robotics. It pairs on-device camera scanning with weather-driven forecasting, safety-gated
multilingual advisories, cross-farm outbreak intelligence, and a geospatial dashboard.
Every requirement in the problem statement is implemented and traceable to code
([`docs/PS_TRACEABILITY.md`](docs/PS_TRACEABILITY.md)).

## Contents

1. [The problem we are solving](#1-the-problem-we-are-solving)
2. [The solution](#2-the-solution)
3. [Scope, stated plainly](#3-scope-stated-plainly)
4. [Honesty about what is real](#4-honesty-about-what-is-real)
5. [Quick start](#5-quick-start)
6. [Tech stack](#6-tech-stack)
7. [Architecture](#7-architecture)
8. [How it actually works](#8-how-it-actually-works)
9. [Design decisions worth knowing](#9-design-decisions-worth-knowing)
10. [The lab — in-development vision research (beta)](#10-the-lab--in-development-vision-research-beta)
11. [Competitive advantages](#11-competitive-advantages)
12. [Target users and societal impact](#12-target-users-and-societal-impact)
13. [Training the model](#13-training-the-model)
14. [Repository layout](#14-repository-layout)
15. [Knowledge base and configuration](#15-knowledge-base-and-configuration)
16. [Future scope and scalability](#16-future-scope-and-scalability)
17. [Revenue model](#17-revenue-model)
18. [Competitor analysis](#18-competitor-analysis)
19. [Traceability to the problem statement](#19-traceability-to-the-problem-statement)

---

## 1. The problem we are solving

### 1.1 The problem, in the field

- **Reactive diagnosis.** Farmers usually detect a disease only when visible damage has
  already ruined the foliage. By then, yield loss is inevitable.
- **Overstretched extension staff.** Agricultural officers cover large territories, so
  on-the-ground expert diagnosis cannot reach every village immediately.
- **Disconnected agronomic signals.** Microclimate shifts, soil moisture and neighbourhood
  outbreak history rarely translate into clear, farm-level daily advice.
- **The chemical cycle.** Fear and delayed diagnosis push farmers into panic-spraying
  broad-spectrum pesticides, raising input costs, creating chemical resistance, and
  contaminating soil and runoff.

### 1.2 Official problem statement (PS26131)

> Farmers often recognise crop diseases or pest infestations only after visible damage has
> spread. Extension staff may cover large areas, while laboratory diagnosis and expert
> advice may not be immediately available. Weather, crop stage, variety, soil condition and
> local pest history influence risk, but these inputs are rarely combined into actionable
> farm-level alerts. Incorrect diagnosis may lead to delayed treatment, excessive or
> inappropriate pesticide use, increased cultivation cost, residue concerns and yield loss.
> The challenge is to provide timely, reliable and locally relevant detection, forecasting
> and management support.

**Expected solution (official).** A farmer- and extension-worker-friendly crop-health system
supporting image-based symptom identification, pest-trap or sensor inputs, weather-based
risk forecasting, geospatial hotspot mapping, expert validation, and multilingual
advisories. It should recommend integrated pest and disease management (IPDM) actions, safe
input usage, referral to extension officers or laboratories, and follow-up monitoring; learn
from field confirmations; and provide dashboards for agriculture officials.

---

## 2. The solution

CropGuard delivers a closed loop: **Forecast → Triage → Detect → Verify → Monitor → Learn.**

### For farmers

- **The "should I walk my field today?" home screen** ([`HomePage.jsx`](frontend/src/pages/HomePage.jsx)).
  Instead of a blank camera viewfinder, the app opens on a single traffic light — calm /
  watch / act — with plain-language instructions in Marathi, Hindi, Bengali or English. It
  fuses the weather forecast with cross-farm outbreak propagation, so a confirmed blight
  nearby raises your risk before you have detected anything yourself.
- **Proactive risk alerts** ([`RiskPage.jsx`](frontend/src/pages/RiskPage.jsx)) — weather-driven
  epidemiological modelling that warns days before spores visibly manifest.
- **On-device live video scanner** — edge AI running inside the browser at zero per-frame
  server cost, operational in rural dead zones with no internet connection.
- **Photo upload** as an alternative to live scanning, routed through the same pipeline.
- **Safe, localized advisories** — non-hallucinatory IPDM guidance with an explicit
  *do not spray* directive for healthy crops.
- **Follow-up and resistance tracking** — check-ins on treatment efficacy that escalate
  repeated failures to a laboratory rather than prescribing a heavier chemical dose.

### For extension officers and state officials

- **Explainable evidence auditing** — click through any risk score to the exact
  meteorological rules and modifier weights that triggered the alert.
- **Geospatial hotspot mapping** — a cell-by-cell explainability grid alongside
  village-level kernel density heatmaps.
- **Pest-trap sensor ingestion** — telemetry from in-field pheromone traps feeding
  tuber-moth counts into the map and the risk engine.
- **Human-in-the-loop review queue** — officers validate AI detections, and verified cases
  feed back into the training lifecycle.
- **Officer dashboard** — district trends, high-risk district ranking, and a live-only /
  demo data switch.

---

## 3. Scope, stated plainly

**The deployed detector covers potato only, with three classes:**
`potato_early_blight`, `potato_late_blight`, `potato_healthy`.

That is a deliberate choice, not a shortcut:

- Late blight is the textbook weather-driven epidemic — the **Smith Period** risk model is
  defined for it, so the detection and forecasting halves of this system reinforce each
  other on the same crop.
- Potato is a major Maharashtra rabi crop with real extension demand.
- Clean training imagery exists (PlantVillage), so the model can actually be trained on a
  free Kaggle GPU in one session.

Adding a crop is a dataset-and-retrain task: extend `ml/data.yaml`,
`backend/app/services/taxonomy.py`, and the knowledge base. No architectural change.

Two **further, separate detectors** live under the menu's *In the lab · beta* group and are
described in [section 10](#10-the-lab--in-development-vision-research-beta).

---

## 4. Honesty about what is real

The system reports its own degraded components at `GET /meta/health`, and the UI shows a
banner. On a fresh clone, with no weights and no API keys:

| Component | Fresh clone behaviour |
|---|---|
| Image detection | **Unavailable** — cases are routed to the expert queue rather than given a guessed diagnosis. |
| Weather | Deterministic **synthetic feed**, flagged `synthetic: true` in every response. |
| Risk models | **Fully working** — the agronomic models need no training data. |
| Advisory / RAG | **Fully working** — BM25 retrieval if ChromaDB is not installed. |
| Marathi / Hindi / Bengali | **Fully working** — template catalog, no API key needed. |
| In-app assistant (`/chat`) | **Canned fallback replies** without `GEMINI_API_KEY`; `GET /chat/status` says which mode it is in. |
| XGBoost risk layer | **Inactive by design** — no historical outbreak data exists yet to train it honestly. It activates as confirmed cases accrue: `scripts/export_risk_dataset.py` builds a leakage-safe training set from them, `ml/train_risk_xgb.py` trains it (both refuse fabricated or too-little data), and the backend loads the artifact automatically. |

Nothing fabricates a result to look complete.

`GET /meta/health` reports two separate lists, because conflating them misleads in both
directions:

- **`degraded`** — something that should work and does not. Only these raise a banner.
- **`by_design`** — a documented, deliberate state. Template-only advisories and an
  untrained XGBoost layer are the specification, not faults.

---

## 5. Quick start

Requires Python 3.10-3.13 and Node 18+.

```bash
# 1. Backend
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -r backend/requirements.txt
# First-time setup ONLY - creates .env if you don't have one, never overwrites an existing one.
# Skip this entirely if .env already exists (overwriting it wipes your OPENWEATHER_API_KEY).
#   bash:        [ -f .env ] || cp .env.example .env
#   PowerShell:  if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Then add OPENWEATHER_API_KEY to .env.

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
pytest backend/tests -q      # 172 tests, no network, no trained model needed

cd frontend && npm test      # 59 tests: browser decoder parity, quality gate,
                             # verdict stabilizer, unique plant tracker,
                             # canopy airflow, real onnxruntime-web run
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
`weather_observations` cache, which fills up as it runs, and any remaining gap is synthetic
backfill that the response reports explicitly.

---

## 6. Tech stack

### Client interfaces (frontend)

| Technology | Role |
|---|---|
| **React (Vite)** | Farmer home, live scanner, risk surfaces, officer review queue, dashboard, the lab modules |
| **onnxruntime-web (WebAssembly)** | Executes computer-vision models entirely in browser memory on ordinary phone CPUs |
| **Leaflet & Mapbox GL** | Geospatial rendering, clustering, kernel density heatmaps |
| **Recharts** | Epidemiological trendlines, humidity-duration charts, trap-count curves |

### Application and inference serving (backend)

| Technology | Role |
|---|---|
| **FastAPI** | Asynchronous REST API serving `/detect`, `/risk`, `/advisory`, `/home/overview`, `/croprow/*`, `/crophealth/*` |
| **SQLite / PostgreSQL** | Cases, follow-ups, trap readings, training samples, weather cache |
| **Uvicorn** | ASGI serving layer |
| **ONNX Runtime (CPU)** | Server-side inference path, same artifact the browser runs |

### Computer vision models

| Model | Role |
|---|---|
| **YOLOv8s (potato pathology)** | Disease detector trained on combined laboratory and field splits, exported to ONNX for CPU-only serving |
| **YOLOv8 CropRow (cultivator guidance)** | Single-class plant localizer wired to [`plantTracker.js`](frontend/src/lib/plantTracker.js) |
| **YOLOv8 CropHealth (vigour triage)** | Two-class healthy / unhealthy plant detector over the same footage |
| **Ultralytics & PyTorch** | Cloud-isolated training environment (Kaggle GPU), never the dev laptop |

### Agronomic modelling and advisory

| Technology | Role |
|---|---|
| **Classical agronomy** | Deterministic routines for Smith Period, Beaumont Period, TOMCAST DSV, degree-days |
| **XGBoost + TreeSHAP** | Auxiliary risk refinement layer, hard-capped at ±0.20 |
| **LangGraph RAG engine** | Multi-stage advisory pipeline: retrieve → compose → safety_gate → localize |
| **ChromaDB & BM25** | Hybrid semantic and keyword search over a human-audited markdown knowledge base |
| **Deterministic localization** | Static catalog of 49 messages × 4 languages (Marathi, Hindi, Bengali, English) |

---

## 7. Architecture

```
┌──────────────────────────────┐
│  React frontend (Vite)       │  farmer flow + officer dashboard + Leaflet map
└──────────────┬───────────────┘
               │ REST (/api proxied in dev)
┌──────────────▼───────────────┐
│  FastAPI backend             │
├──────────────────────────────┤
│ POST /detect     │ YOLOv8s via ONNX Runtime (CPU) → class + confidence + bbox
│ POST /detect/frame │ Stateless per-frame inference for the live scanner
│ GET  /detect/model │ Serves the ONNX so the browser can infer on-device
│ GET  /home/overview │ The "should I walk my field today?" traffic light
│ /croprow/*       │ CropRow lab (beta): separate single-class crop localizer for video
│ /crophealth/*    │ CropHealth lab (beta): two-class healthy/unhealthy plant detector
│ POST /risk       │ Smith / Beaumont / TOMCAST / degree-days + OpenWeatherMap
│ POST /advisory   │ LangGraph pipeline over a human-reviewed IPDM knowledge base
│ GET  /hotspots   │ Geo-grid aggregation, confirmed cases weighted above unverified
│ GET  /hotspots/points │ Per-case weighted points for a true density heatmap
│ POST /chat       │ In-app assistant (Gemini server-side; canned replies with no key)
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

Both entry points converge in `backend/app/services/pipeline.py`, so a photo-triggered case
and a proactive weather alert get the same safety gate and the same advisory pipeline:

```
image?  → detection ─┐
                     ├→ risk assessment → TRIAGE → advisory (RAG) → case + follow-up
location → weather ──┘                      │
                                            └→ escalate to expert instead of recommending
                                               a pesticide, when confidence is low, signals
                                               conflict, or a treatment has already failed
```

---

## 8. How it actually works

The flow is meant to feel natural for the farmer and stay conservative behind the scenes:

1. A farmer uses the live scanner, uploads a photo, or the system runs a proactive weather
   check with no image at all.
2. The backend assesses the image and weather data, routing **every** case through one
   safety triage gate in `pipeline.py`. A weather alert can never bypass a safety rule that
   a photo case obeys.
3. The system retrieves guidance from a human-reviewed knowledge base to compose a localized
   advisory, returning the exact KB sections it drew from as citations.
4. To prevent false alarms, the live camera discards blurry and badly exposed frames
   (variance-of-Laplacian blur plus exposure scoring) and requires temporal consensus —
   by default 6 of 10 good frames at ≥55% mean confidence — before issuing a verdict.
5. Nothing is stored until the farmer presses **Accept**, which sends that exact frame
   through the full `/detect` pipeline: same advisory, same triage, same follow-up as a
   photo upload. Discarded scans leave no record at all.
6. Later an officer reviews the case and confirms or corrects the diagnosis. A confirmed
   case becomes a labelled training sample, and a failed follow-up auto-escalates.

---

## 9. Design decisions worth knowing

### 9.1 Risk forecasting is rule-based first, ML second

There is no ready-made labelled dataset linking weather + crop stage + variety + soil +
local pest history to actual outbreak events for Indian crops. So the **primary layer is
published agronomic models** that run deterministically today:

| Model | Target | Criterion |
|---|---|---|
| **Smith Period** (Smith, 1956) | Late blight | 2 consecutive days: min temp ≥ 10 °C **and** ≥ 11 h at RH ≥ 90% |
| **Beaumont Period** (1947) | Late blight | 46 consecutive hours ≥ 10 °C and RH ≥ 75% (earlier, looser warning) |
| **TOMCAST DSV** | Early blight | Daily severity 0-4 from leaf-wetness hours × mean temperature; spray at 15 DSV |
| **Degree-days** | Tuber moth, aphids | Single-triangle accumulation; ~360 DD above 10 °C per tuber-moth generation |

These are then adjusted by **crop stage × variety susceptibility × soil drainage**, plus
confirmed nearby cases and live trap counts.

The **XGBoost + SHAP secondary layer** (`ml/train_risk_xgb.py`) is additive refinement. It
refuses to train on fewer than 200 rows and refuses to save a model scoring below 0.6 AUC,
and it can never move the rule-based score by more than ±0.20 — a thinly-trained model must
not be able to override a fired Smith Period.

The dataset it needs is a by-product of running the system: once expert-confirmed cases
accumulate, `scripts/export_risk_dataset.py` builds the training CSV from them (features
from the weather *before* each case, label from confirmed outbreaks *after* it). It refuses
to export seeded demo rows or synthetic-weather rows unless explicitly forced, so the layer
activates on real evidence or not at all.

### 9.2 Every advisory is traceable and safety-gated

Doses are **parsed from reviewed markdown tables**, never generated. Each advisory returns
the knowledge-base sections it drew from. The triage layer withholds the dose table entirely
when confidence is low, when the image and weather disagree, or when two follow-ups have
already reported a treatment failing (which suggests fungicide resistance, not a bigger
dose).

### 9.3 Marathi, Hindi and Bengali work without an API key

Advisories are assembled from a **translated message catalog**
(`backend/app/services/translate.py`) — 49 messages × 4 languages — so a farmer gets
genuinely native-language guidance with no network, no LLM, and no per-request cost. An LLM
is used only to translate free-text knowledge-base excerpts, and falls back to English
rather than risk a mistranslated dose.

The catalog is checked structurally by `backend/tests/test_translations.py`: right script per
language, placeholders preserved, no entry carrying another entry's text, and no language
silently below 100% coverage. That suite exists because a scripted edit once spliced Bengali
into the wrong entry and every other test still passed.

### 9.4 Hotspots weight expert-confirmed cases above model output

An officer should not deploy staff on unverified AI predictions, but should still see a spike
of pending reports. Confirmed cases count 1.0, unreviewed predictions count 0.4, and both are
reported separately.

The map renders these two ways: a **true density heatmap** (`GET /hotspots/points` returns
each case at its own coordinate with its weight, so a Leaflet canvas heat layer paints a
smooth surface that localises to village clusters instead of snapping to the 5 km grid), and
the explainable **grid** view (`GET /hotspots`) an officer can read cell by cell. The heat
ramp's top of scale is pinned to the "severe" band, so red means the same on both.

The map and dashboard both carry a **Data source** switch. Seeded demo rows (marked
`model_version = "demo-seed"`) exist only so a fresh clone has something to show; **Live
only** excludes them from every panel and the map, so an officer can see exactly what the
real field reports say — which, early on, is deliberately very little — while **Demo + live**
keeps the walkthrough populated. Real cases with no `model_version` are never dropped by the
filter.

### 9.5 ONNX on CPU is the serving path

No torch on the dev laptop, a few hundred ms per image, and the same artifact an offline
on-device build would ship. The export is shape-verified, the decoder is tested against a
real onnxruntime session, and `ml/benchmark_inference.py` measures the latency rather than
asserting it.

### 9.6 The live scanner runs on-device, and refuses to guess

Pointing a phone at a crop is the interaction a farmer actually wants, but a naive version of
it is dangerous: per-frame predictions flicker, and a pesticide decision must not rest on 33
milliseconds of video. So the scanner has three gates:

1. **Quality gate.** Every frame is scored for blur (variance of Laplacian) and exposure
   before the model sees it. Blurred and badly lit frames are discarded and the farmer is
   told what to fix — "hold steady", "move into better light" — rather than being given a
   confident answer computed from mush.
2. **Temporal consensus.** No verdict appears until the model agrees with itself across a
   rolling window of good frames (default: 6 of 10 frames, ≥55% mean confidence). Five
   healthy frames plus one lucky late-blight frame yields *healthy*, not a scare.
3. **Explicit accept.** Nothing is stored until the farmer presses Accept, which sends that
   exact frame through the full `/detect` pipeline — same advisory, same triage, same
   follow-up as a photo upload. Discarded scans leave no record at all.

Inference runs **in the browser** via onnxruntime-web: no network per frame, no server cost,
and scanning keeps working on a bad field connection or none at all. The WASM runtime is
served from our own origin rather than a CDN, precisely so the offline claim is real. If WASM
cannot start, or no model is installed, it falls back to `/detect/frame` and then to plain
photo capture — and says which mode it is in.

The browser decoder is a deliberate mirror of `services/detector.py`, and
`frontend/src/lib/__tests__/` asserts they agree on the same numbers — including one test
that runs a real ONNX model through onnxruntime-web and checks it decodes the identical box
the Python server does. Two implementations of the same maths is a bug waiting to happen; the
tests are what keep them honest.

### 9.7 Detection thresholds encode an asymmetric cost

A single `conf=0.25` assumes a false positive and a false negative cost the same. Missing late
blight can cost the field; a false positive costs a spray and is *already* caught by the
triage layer, which withholds the dose table below the low-confidence threshold. So disease
classes are tuned for recall and `healthy` for precision, per class — see
`ml/tune_thresholds.py`.

### 9.8 Hyperlocal microclimate sensing (experimental)

The phone's live camera doubles as a passive in-field airflow proxy
([`canopyAirflow.js`](frontend/src/lib/canopyAirflow.js)). Classical pixel maths cancels
camera shake and reads the independent leaf motion that survives, grading canopy airflow as
still / light / breezy — a signal a weather station 20-30 km away cannot see. Still air means
dew lingers, which stretches leaf wetness, which is exactly the input the Smith Period
(≥11 h) and TOMCAST models read. A strict guardrail keeps it safe: a breeze may raise concern
but can never "un-fire" a blight rule that already met the observed humidity, and the
adjustment is capped like every other modifier.

---

## 10. The lab — in-development vision research (beta)

A deliberately walled-off research module under the menu's *In the lab · beta* group. It
answers a **robotics** question, not a pathology one: *where are the crop plants for a
cultivator-mounted camera*, and *does each one read as healthy*. It generates zero database
cases, zero chemical advisories and zero farmer records.

### 10.1 Crop row scan — plant localization

**Crop row scan** ([`croprow/`](croprow/)) is a single-class crop (lettuce) *localizer* kept
apart from the potato stack: its own weights, its own `/croprow` endpoints, its own class
list, no case, no advisory, no database write.

- **Two inputs, one detector.** A live camera (the same camera picker as Live scan) or an
  uploaded video clip, both drawing boxes as the footage plays.
- **A unique count that does not double-count.** Per-frame boxes carry no identity, so
  summing them would count a plant once per frame it is visible. A lightweight IoU tracker
  ([`frontend/src/lib/plantTracker.js`](frontend/src/lib/plantTracker.js)) matches each
  frame's boxes to the previous frame's and ticks the total up only for a genuinely new
  plant. It is geometry-only, so a plant that leaves and returns is counted again — the UI
  says so, and the behaviour is pinned by tests.
- **The same honest serving story.** On-device ONNX from `GET /croprow/model` is preferred
  (offline, no per-frame server call), falling back to `/croprow/frame` and then to a clear
  "model not installed" message. Weights are not committed — export the trained model once
  with `python croprow/export_onnx.py`.
- **Browser-playable video.** Browsers cannot decode the LettuceMOTS clips' MPEG-4 Part 2
  codec, so `croprow/convert_videos.py` transcodes them to H.264 and
  `croprow/generate_video.py` writes H.264 directly.

### 10.2 Crop health scan — healthy / unhealthy triage

**Crop health scan** ([`croprow_disease/`](croprow_disease/)) answers the follow-up question
on the same footage: *is this plant healthy*. It is a two-class (`healthy` / `unhealthy`)
detector on its own `/crophealth` endpoints, reusing the croprow lab's shape exactly — live
camera or uploaded clip, boxes drawn per frame, no case, no advisory, no database write.

- **Two classes, so the decode contract differs.** This model emits 4 box + **2** class
  scores per prediction where croprow emits 4 + 1, and a box is classified by the argmax of
  the two class columns. A serving path written against the single-class model does not error
  on these outputs, it just mislabels them, so
  `backend/app/services/crophealth_detector.py` is a separate decoder and
  `backend/tests/test_crophealth.py` pins which class each box comes back as.
- **Suppression runs per class.** A healthy and an unhealthy plant that overlap are two
  findings. Pooling them would silently delete the lower-scoring one, which is exactly the
  case where the two labels disagree and it matters most. The server and
  `frontend/src/lib/yoloDecode.js` agree on this.
- **The count is per class, and it is voted.** The same tracker counts each plant once, and
  each track keeps a tally of the labels it has been given, so a plant that flickers on one
  blurred frame is reported as whatever it has been called most often, not as whatever the
  last frame said. Boxes are coloured green and red **and labelled in words**, because
  red/green alone is the one pair a colour-blind user cannot separate.
- **It is vigour triage, not a diagnosis, and the UI says so.** The training labels came from
  a leaf-colour rule over real annotation polygons
  ([`croprow_disease/health.py`](croprow_disease/health.py)), not from an agronomist. An
  "unhealthy" mark means the canopy reads as off, not that a disease is confirmed. The class
  names are read from the weights themselves, and a model that does not expose this class
  pair is served with its boxes but flagged as untrustworthy for labels rather than quietly
  relabelled.

### 10.3 Current limitations and the plan

Both modules are **in development** by design: the training notebooks ship unrun, the weights
are not committed, and the features are grouped under "In the lab · beta" so they read as
previews rather than shipped tools. The health labels are derived from a colour rule over
lettuce annotation polygons because no suitable agronomist-labelled healthy/unhealthy crop-row
dataset was available; replacing that rule with expert labels is the next step, followed by
mounting the pair on a real cultivator to steer inter-row weeding and remove unhealthy plants
in the same pass.

---

## 11. Competitive advantages

- **Precaution is better than cure.** Most crop tools react after damage shows. CropGuard
  reads the weather building up around a field using published agronomic models — Smith,
  Beaumont, TOMCAST — and warns days before the first spot appears on a leaf. The alert is
  not a black box: every model that fired and every reason behind the score is shown in plain
  language.
- **Hyperlocal microclimate sensing (experimental).** The phone camera becomes a passive
  airflow proxy, grading canopy airflow as still / light / breezy — a signal a distant weather
  station cannot see — and it is wired into exactly the leaf-wetness input the blight models
  read. A guardrail prevents it from ever cancelling a rule that already fired.
- **Offline ready.** Live camera scanning and multilingual advisories run with no network and
  no paid API calls. The WASM runtime is served from the app's own origin, not a CDN,
  precisely so the offline claim is real.
- **Honest AI.** The dashboard separates broken components (`degraded`) from deliberate design
  limits (`by_design`), so nobody has to guess whether a number came from a real model or a
  fallback. No result is fabricated to look complete.
- **A learning flywheel that improves in the field.** Every case an officer confirms or
  corrects becomes a labelled training sample. `ml/export_feedback.py` packages them for
  retraining and warns when a batch is too small or skewed to one district. The retrain stays
  a deliberate human step — retraining on unexamined field data is how a model quietly
  degrades.
- **Two decoders, one behaviour.** The browser (JavaScript) and server (Python) YOLO decoders
  are tested against each other case-for-case, including against a real onnxruntime-web
  session, so both produce the identical bounding box.

---

## 12. Target users and societal impact

Built for farmers, local extension workers, and state agriculture officials.

- **Reduces crop loss by predicting threats early.** A fired Smith Period is an *infection*
  event, not a visible one, so the warning arrives before the symptoms do.
- **Promotes targeted pesticide use** — explicitly advising when *not* to spray a healthy
  crop, withholding dose tables when confidence is low, and routing repeated treatment
  failures to a laboratory instead of a heavier spray.
- **Empowers officials to deploy staff efficiently** on verified hotspot data, with confirmed
  cases weighted above unverified model output.
- **Improves surveillance coverage** — every photo becomes a georeferenced case, and pest-trap
  ingestion adds a second independent signal stream.

---

## 13. Training the model

**Never train locally** — the dev machine has 16 GB RAM and very little C: space, and training
belongs on a GPU. Only the exported weights (a few MB) come back down.

Open `ml/notebooks/kaggle_train_potato_yolo.ipynb` on **Kaggle** (GPU T4 ×2, internet on), add
the `abdallahalidev/plantvillage-dataset` input, and run it through. Kaggle rather than Colab:
Colab reclaims GPUs from idle sessions and would kill a 100-epoch run with no checkpoint,
while Kaggle gives a 30 hr/week quota and a 12 hr session limit.

Equivalent CLI:

```bash
python ml/prepare_dataset.py --plantvillage <plantvillage-path> --annotated <plantdoc-path> \
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
| **Class imbalance** | PlantVillage + PlantDoc potato is ~6.4:1 against `healthy` — the class that says *do not spray*. `--cap-train` caps majority classes in the train split only; `--oversample-min` lifts the minority. Measured **6.56:1 → 1.00:1**, printed before and after. |
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
`python ml/export_feedback.py --out datasets/feedback_01` packages them for the next training
run, and warns when a batch is too small or dominated by one district. It is deliberately a
manual step — retraining on unexamined field data is how a model quietly degrades.

---

## 14. Repository layout

```
backend/app/
  routers/       detect · risk · advisory · hotspots · sensors · review · followup
                 dashboard · home · chat · croprow · crophealth · meta
  services/      detector · weather · risk_models · risk_engine · risk_secondary
                 knowledge_base · advisory · triage · translate · pipeline · geo · taxonomy
                 home_overview · crophealth_detector
  data/kb/       IPDM knowledge base (human-reviewed markdown - edit this, not the code)
  models.py      cases · follow-ups · sensor readings · training samples · weather cache
backend/tests/   172 tests: agronomic models, triage rules, ONNX decoding (fake and
                 real onnxruntime session), per-class thresholds, translation
                 integrity across 4 languages, live-scanner endpoints, crophealth
                 decode contract, full API
ml/              dataset prep · training · evaluation · threshold tuning · benchmarking
                 ONNX export · feedback export · risk XGBoost
ml/DATASETS.md   dataset comparison, imbalance analysis, provenance
ml/notebooks/    Kaggle training notebook (potato, 3 classes, 100 epochs)
frontend/src/    React app - live scanner, farmer flow, risk page, Leaflet map,
                 dashboard, review queue, CropRow + CropHealth labs (beta)
frontend/src/lib/ yoloDecode (browser mirror of the server decoder) · liveDetector
                 (onnxruntime-web, parameterised per model) · plantTracker (unique
                 plant counting) · frameQuality · stabilizer · canopyAirflow · i18n
croprow/         CropRow lab (in development): a single-class crop (lettuce) localizer,
                 separate from ml/ - training notebooks, best.pt, export_onnx.py,
                 convert_videos.py + generate_video.py (H.264) video helpers
croprow_disease/ CropHealth lab (in development): a two-class healthy/unhealthy plant
                 detector over the same footage - health.py (the colour rule that
                 derives the labels), dataset.py, training notebooks, export_onnx.py
scripts/         demo data seeding · risk-dataset export for the XGBoost layer · dev runners
docs/            architecture notes and PS traceability matrix
```

---

## 15. Knowledge base and configuration

`backend/app/data/kb/*.md` holds the IPDM content: symptoms, dose tables, cultural practice,
safe-use rules, referral criteria. It is markdown with YAML front matter so an agronomist can
review and correct it in a pull request without touching code.

**Every dose carries `review_status: needs_local_validation`.** The figures are the commonly
published ICAR/CPRI extension rates, but they must be checked against the CIB&RC product label
and the local KVK before this system is used by a real farmer. After editing, run
`POST /advisory/reindex`.

Configuration lives in `.env` — see `.env.example`. Everything runs without any key; keys
upgrade components from their documented fallbacks to live data.

---

## 16. Future scope and scalability

- **More crops and classes.** Adding a crop is a dataset-and-retrain task: extend
  `ml/data.yaml`, `backend/app/services/taxonomy.py`, and the knowledge base. Tomato is the
  natural next crop — it shares late blight and the Smith Period.
- **A dedicated field metric.** Expand the field-image dataset into a standalone
  field-condition validation split, so accuracy is always quoted on real phone photos rather
  than laboratory imagery.
- **Activate the XGBoost + SHAP risk layer.** It turns on once enough real Indian outbreak
  data accrues; `scripts/export_risk_dataset.py` already builds a leakage-safe training set
  from confirmed cases. The layer stays capped at ±0.20 so it can refine, but never override,
  a validated agronomic rule.
- **Real weather history.** Backfill the Smith Period window from a paid or archival weather
  source instead of relying on the system's own accumulating cache.
- **Agronomist-labelled crop-row health.** Replace the colour-rule labels in
  `croprow_disease/health.py` with expert annotations, then mount the crop-row pair on a real
  cultivator to steer inter-row weeding and remove unhealthy plants in the same pass.

---

## 17. Revenue model

CropGuard is built strictly as a **public good** for the Government of Maharashtra under the
Smart India Hackathon. There is no subscription, no marketplace and no monetization model.
The design goal is the opposite: minimise operating cost — free APIs, on-device inference, no
per-request LLM calls — so the platform can be run at state scale on a public budget while the
value accrues to farmers.

---

## 18. Competitor analysis

### 18.1 Landscape

| Product | Reach | Limitation |
|---|---|---|
| **Plantix** (global benchmark) | 10 M+ downloads, ~8 M annual active users, 26,000+ daily scans, 30 crops, 780+ diseases | Strictly reactive (detects after tissue is dead), cloud-dependent, no canopy sensing, no pre-symptom forecasting |
| **MahaVISTAAR AI** (Maharashtra state voice AI) | 2.5 M+ farmers, 20,000+ daily queries, 19 languages/dialects, works without a smartphone | Conversational only — no computer vision, no row tracking, no localized spread modelling |
| **BharatAgri / AgroStar** (commercial advisory & e-commerce) | 5.5 M+ and 10 M+ downloads | Revenue is tied to selling agrochemicals — an inherent incentive to prescribe sprays over IPM |
| **Agrio** (precision agriculture) | ~800,000 global users, satellite NDVI + macro spore models | Expensive enterprise tier, bandwidth-hungry, complex UX, no Indian dialect support, no on-device canopy sensing |
| **CROPSAP Maharashtra** (legacy state surveillance) | Statewide, field scouts logging trap counts manually | Heavy human dependency, slow turnaround, village-level advisories rather than farm-level guidance |

### 18.2 Feature comparison

| Feature | CropGuard | Plantix | Agrio | AgroStar / BharatAgri | MahaVISTAAR / CROPSAP |
|---|---|---|---|---|---|
| **First screen** | "Should I walk my field today?" traffic light | Blank camera / upload form | Field polygon / satellite map | E-commerce banner / chat feed | Voice prompt / text bulletin |
| **Operational paradigm** | Pre-symptomatic forecast + real-time video consensus | Reactive still photo | Macro-satellite forecast + reactive photos | Reactive photo upload | Periodic manual scout reports |
| **Disease modelling** | Agronomic science first, ML second (Smith, Beaumont, TOMCAST, DD + SHAP) | Black-box deep CNN | Cloud predictive weather models | Human agronomist / basic rules | Manual scientist review of traps |
| **Explainability** | Full evidence matrix — exact rule triggers and modifier weights | Opaque confidence percentage | Black-box risk index | Informal chat explanation | Published PDF / text advisories |
| **Micro-canopy sensing** | Camera pixel transition — zero-hardware local wind and wetness proxy | Generalized weather APIs 20-30 km away | Satellite and regional weather grid | 3rd-party weather APIs | Manual rain gauges and pheromone traps |
| **Spatial outbreak pressure** | Cross-farm aggregation, privacy-preserving 5 km / 15 km radius | Regional cloud heatmap | Satellite macro-spread tracking | Isolated user logs | Village-level scout aggregates |
| **Network / edge** | Offline edge AI, on-device ONNX runtime | Needs internet to upload | Needs internet for satellite/inference | Needs an active data connection | Cellular voice / web portal |
| **Chemical stewardship** | Safety-gated withholding — blocks dosage on low confidence or suspected resistance | Recommends commercial pesticides | Recommends spray windows | Commercial bias toward pesticide sales | Non-commercial public advisories |
| **Ecosystem** | Dual-sided: farmer app + state officer GIS portal | B2C farmer-only, paid enterprise APIs | Enterprise B2B / large farms | B2C farmer marketplace | B2G government portal only |
| **Model evolution** | Human-in-the-loop, officer-validated review queue | Centralized batch training on uploads | Centralized cloud updates | Manual agronomist adjustments | Manual periodic advisory updates |
| **Robotics / spatial lab** | CropRow + CropHealth labs (beta), IoU plant tracking for implements | None | None | None | None |

### 18.3 Context: adoption and measured impact

Published sector figures that frame the opportunity (industry and government sources, not our
own measurements):

- **Adoption.** Roughly 10-15% of smartphone-owning Indian farmers actively use an
  agriculture-specific app; ~70% of educated farmers own a smartphone, with the remainder
  getting farming information via WhatsApp groups and YouTube. Maharashtra leads digital
  onboarding under the MahaAgri-AI Policy (2025-2029), and MahaVISTAAR AI has onboarded 3 M+
  farmers, with AgriStack generating millions of land-verified IDs in the state.
- **Productivity.** Precision-agriculture and AI advisory tools are associated with a 15-30%
  average yield increase (up to ~40% in localized Maharashtra sugarcane and horticulture
  pilots), 15-25% lower input costs, and 20-35% income uplift when paired with market linkage.
- **Wastage.** Precision management cuts excess chemical runoff and over-irrigation by 20-30%;
  output-linkage platforms reduce post-harvest losses from 25-40% down to 5-8%; and weather
  and pest early-warning systems prevent an estimated 10-15% of output loss during erratic
  climate events.

CropGuard targets the first and last of these directly: pre-symptomatic warning to prevent
harvest loss, and safety-gated advisories to cut unnecessary chemical input.

---

## 19. Traceability to the problem statement

See [`docs/PS_TRACEABILITY.md`](docs/PS_TRACEABILITY.md) — every required capability in the
official "Expected Solution" text mapped to the code that implements it. A longer narrative
version of this document lives in [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md), and the
architecture notes in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
