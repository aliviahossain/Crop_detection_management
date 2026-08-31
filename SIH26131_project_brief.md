# SIH 2026 — PS26131: Crop Disease & Pest Detection System
**Organization:** Government of Maharashtra (Maharashtra State Innovation Society, Dept. of Skills, Employment, Entrepreneurship and Innovation)
**Category:** Software | **Theme:** Agriculture, FoodTech & Rural Development | **Idea submission deadline:** 20 September 2026 (confirm what's actually due at this stage — see Section 6)

---

## 1. Official Problem Statement

**Problem Description:**
Farmers often recognise crop diseases or pest infestations only after visible damage has spread. Extension staff may cover large areas, while laboratory diagnosis and expert advice may not be immediately available. Weather, crop stage, variety, soil condition and local pest history influence risk, but these inputs are rarely combined into actionable farm-level alerts. Incorrect diagnosis may lead to delayed treatment, excessive or inappropriate pesticide use, increased cultivation cost, residue concerns and yield loss. The challenge is to provide timely, reliable and locally relevant detection, forecasting and management support.

**Expected Solution / Outcome (official):**
A farmer- and extension-worker-friendly crop-health system that supports:
- image-based symptom identification
- pest-trap or sensor inputs
- weather-based risk forecasting
- geospatial hotspot mapping
- expert validation
- multilingual advisories

The system should recommend integrated pest and disease management (IPDM) actions, safe input usage, referral to extension officers or laboratories, and follow-up monitoring. It should learn from field confirmations and provide dashboards for agriculture officials.

**Expected outcomes:** earlier detection, reduced crop loss, more targeted pesticide use, faster extension response, improved surveillance coverage, better planning of preventive interventions.

---

## 2. Feature Breakdown (mapped to required system components)

| # | Required Component | What It Means | Suggested Tech | Priority |
|---|---|---|---|---|
| 1 | Image-based symptom identification | Photo → disease/pest class + confidence + bounding box | YOLOv8n/v11n, trained on PlantVillage + PlantDoc (field-condition images) | **MVP — must-have** |
| 2 | Weather-based risk forecasting | Predict disease/pest risk *before* visible symptoms, using weather + crop stage + variety + soil + local pest history | Rule-based agronomic risk models (e.g. Smith Period for late blight, degree-day thresholds for pest emergence) as the primary logic, since no ready-made labeled dataset links weather+crop+soil to actual outbreak events for Indian crops. XGBoost + SHAP layered on top only where real historical data can reweight the thresholds (check CROPSAP Maharashtra pest surveillance bulletins for usable data). Weather API: OpenWeatherMap or Tomorrow.io (IMD has no practical public API for this) | **MVP — strong differentiator, but scope the model honestly (see Section 4)** |
| 3 | IPDM recommendation engine | Given detected disease/pest + risk level, recommend treatment, dosage, safe pesticide use | RAG over agri-extension knowledge base (LangGraph + ChromaDB). Note: the knowledge base itself is real manual effort — sourcing accurate, safe treatment/dosage guidance per disease/pest class the model covers, not just a config step | **MVP — must-have, budget real effort for content sourcing** |
| 4 | Pest-trap / sensor inputs | Ingest data from physical traps/sensors as an additional signal | FastAPI ingestion endpoint, simple schema (device_id, reading, timestamp, geo) | Can start as a mocked/simulated feed, wire to real hardware later |
| 5 | Geospatial hotspot mapping | Visualize disease/pest clusters across a region | React + Leaflet/Mapbox, aggregate confirmed cases by geo-cell | Core differentiator |
| 6 | Expert validation workflow | Human (extension officer) confirms/corrects AI diagnosis | Review queue UI, simple approve/reject/correct actions, feeds back into training data | Core |
| 7 | Multilingual advisories | Output guidance in regional languages (Marathi priority, given Maharashtra) | Translation API or LLM-based localization layer | High judge/user appeal, moderate effort |
| 8 | Safe input usage + referral logic | Flag when case should escalate to lab/expert instead of self-treatment (e.g. low confidence, unusual pattern) | Rule-based triage on top of model confidence + risk score | **Must-have** (ties diagnosis to safety) |
| 9 | Follow-up monitoring | Track whether recommended treatment worked over time | DB table: case_id, status, follow_up_date, outcome | Core |
| 10 | Learns from field confirmations | Model improves using expert-corrected labels | Feedback loop: log corrections → periodic retraining job | Longer-term, depends on volume of confirmed field data |
| 11 | Officer dashboard | Aggregate view of detections, hotspots, trends for agriculture officials | React dashboard, charts (Recharts), filters by district/crop/disease | Core differentiator |

---

## 3. Suggested Build Grouping (by dependency, not by time)

**Core loop — everything else depends on this working end-to-end:**
1. Upload/capture crop image → YOLO detects disease/pest → returns class + confidence
2. Risk assessment → given location + crop + stage → outputs risk score (low/med/high) even without an uploaded image (proactive alert use case)
3. Recommendation engine → combines detection + risk → outputs IPDM advice + safe-use notes + escalate-to-expert flag when confidence is low
4. Basic frontend (farmer-facing): photo upload, risk check, advisory display

**Builds on the core loop once it's stable:**
5. Geospatial hotspot map (can use simulated/sample confirmed-case data initially, swap in real data as it accumulates)
6. Officer dashboard (aggregated stats)
7. Multilingual output (Marathi minimum, via LLM translation)

**Independent tracks — can be developed in parallel or added incrementally:**
8. Pest-trap/sensor ingestion (mocked API first, real hardware integration later)
9. Expert validation workflow (UI + queue; live retraining is a separate, later effort)
10. Follow-up monitoring (schema first, populate as field data comes in)

---

## 4. Technical Architecture (proposed)

```
┌─────────────────┐
│  Frontend (React) │  farmer app + officer dashboard
└────────┬─────────┘
         │ REST
┌────────▼─────────┐
│   FastAPI backend  │
├───────────────────┤
│ /detect (image)   │──▶ YOLOv8/v11 inference (ONNX export for CPU speed)
│ /risk (weather)   │──▶ XGBoost model + weather API call
│ /advisory         │──▶ RAG (LangGraph + ChromaDB) over IPDM knowledge base
│ /hotspots         │──▶ Aggregation query → geo-clustered case data
│ /sensors          │──▶ Ingest endpoint (trap/sensor data)
│ /review           │──▶ Expert validation queue (CRUD)
└────────┬──────────┘
         │
┌────────▼─────────┐
│   Database (Postgres/SQLite) │  cases, users, feedback, sensor readings
└───────────────────┘
```

**Training pipeline (separate from serving):**
- Dataset: PlantVillage (~54k images, 38 classes) + PlantDoc (field-condition images) hosted/annotated via Roboflow
- Training: Kaggle Notebooks (free GPU, 30hr/week quota) — more reliable than Colab for long runs; use Colab for quick experiments
- Export: `best.pt` → ONNX for fast CPU inference in the FastAPI serving layer
- Local machine only handles: code, API serving, frontend — never raw dataset or training checkpoints (disk constraint: 16GB RAM, very limited C drive)

**Risk model — realistic scoping:**
- There is no ready-made labeled dataset linking weather + crop stage + variety + soil + local pest history to actual disease outbreaks for Indian crops, so "just train XGBoost on it" is not viable as the primary approach.
- **Primary layer:** established agronomic risk models — e.g. the Smith Period for potato/tomato late blight (based on temperature + relative humidity thresholds over consecutive days), degree-day accumulation models for pest emergence timing. These are published, validated formulas that can run as deterministic rules today.
- **Secondary layer:** XGBoost + SHAP to reweight or adjust those rule-based thresholds using whatever real historical data can be sourced (check CROPSAP Maharashtra pest surveillance bulletins, ICAR/NCIPM data) — this is additive refinement, not the foundation.
- Features for the secondary layer, once data is available: temperature, humidity, rainfall (recent + forecast), crop stage, variety, soil condition, local historical pest incidence
- Weather API: OpenWeatherMap or Tomorrow.io — not IMD, which has no practical public API for rapid integration

---

## 5. Build Order (by dependency)

1. Dataset prep (Roboflow) + start YOLO training on Kaggle, in parallel with backend scaffolding (FastAPI routes, DB schema)
2. Rule-based agronomic risk logic (Smith Period / degree-day models) + weather API integration — this can be built and tested before any historical outbreak data is sourced
3. RAG/advisory layer — build the IPDM knowledge base (sourcing accurate, safe treatment/dosage guidance per disease/pest class — this is real content work, not just a config step), wire into LangGraph
4. Frontend — farmer flow (upload → detect → advisory) first, officer dashboard second
5. Geospatial map + multilingual layer
6. XGBoost secondary risk layer, once real historical pest/outbreak data has been sourced (CROPSAP/NCIPM) — treat this as a later refinement, not a blocker for the core loop
7. Integration testing, pitch material tying every feature back to the "expected outcomes" line (earlier detection, reduced crop loss, targeted pesticide use, faster extension response)

---

## 6. Notes for the Agent

- Team constraint: local dev machine has 16GB RAM and very limited C drive space — do not suggest local YOLO training or heavy local dataset storage; use cloud (Kaggle/Colab) for training, only pull trained weights (`best.pt`, few MB) locally.
- Stack preferences already in use: LangGraph, ChromaDB, RAG pipelines, FastAPI, PyTorch/ResNet, XGBoost, SHAP, React, Flask/Streamlit — prefer these over introducing new frameworks unless there's a clear gap (e.g. Leaflet/Mapbox for maps has no existing equivalent in the stack).
- Don't default to "train an ML model" for the risk-forecasting component without first checking whether labeled outbreak data actually exists — see Section 4 for the rule-based-first approach.
- Judges expect AI integration and reward on-device/offline capability — consider noting ONNX/offline-capable inference as a talking point even if full offline mode isn't built initially.
- Every feature should be traceable back to a line in the "Expected Solution" text above — this matters for scoring since evaluators check solution-to-PS alignment.
- Verify on sih.gov.in what is actually due by the 20 September 2026 deadline (idea/concept submission vs a working prototype) before treating any build sequencing here as time-boxed to that date.
