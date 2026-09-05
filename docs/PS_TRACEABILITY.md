# PS26131 Traceability Matrix

Every capability named in the official problem statement, mapped to the code that
implements it and the endpoint that demonstrates it. Section 6 of the project brief
flags this explicitly: evaluators check solution-to-PS alignment.

## Required components (Expected Solution text)

| # | Required by the PS | Implemented in | Demonstrate with | Status |
|---|---|---|---|---|
| 1 | **Image-based symptom identification** | `services/detector.py` (ONNX Runtime, letterbox + per-class NMS), `routers/detect.py`, plus in-browser inference via `frontend/src/lib/liveDetector.js` | `POST /detect` (photo) · `POST /detect/frame` (live) · the **Live scan** page | Serving layer complete and tested, including real-time on-device scanning; needs weights from the Kaggle run |
| 2 | **Pest-trap or sensor inputs** | `models.SensorReading`, `routers/sensors.py`, consumed by `risk_engine._trap_pressure` | `POST /sensors`, `POST /sensors/batch`, `GET /sensors/summary` | Complete; trap counts feed tuber-moth risk and appear on the map |
| 3 | **Weather-based risk forecasting** | `services/risk_models.py` (Smith, Beaumont, TOMCAST, degree-days), `services/risk_engine.py`, `services/weather.py` | `POST /risk`, `GET /risk/models`, `GET /risk/weather` | Complete; runs with no training data by design |
| 4 | **Geospatial hotspot mapping** | `services/geo.py`, `routers/hotspots.py`, `frontend/src/pages/MapPage.jsx`, `frontend/src/lib/heatLayer.js` | `GET /hotspots`, `GET /hotspots/points` (density heatmap), `GET /hotspots/geojson` | Complete; grid and true density-heatmap views, GeoJSON also opens in QGIS |
| 5 | **Expert validation** | `routers/review.py`, `models.TrainingSample`, `frontend/src/pages/ReviewPage.jsx` | `GET /review/queue`, `POST /review/{id}` | Complete |
| 6 | **Multilingual advisories** | `services/translate.py` (en/mr/hi/bn catalog, 49 messages × 4 languages), `services/advisory.py` localize node | `GET /meta/languages`; `language=mr\|hi\|bn` on any endpoint | Complete; all four languages at 100% coverage, no API key required, integrity-tested |
| 7 | **Recommend IPDM actions** | `data/kb/*.md`, `services/knowledge_base.py`, `services/advisory.py` (LangGraph) | `POST /advisory` | Complete; doses parsed from reviewed markdown, citations returned |
| 8 | **Safe input usage** | `data/kb/safe_input_usage.md`, `advisory.node_safety` | Safety block on every advisory | Complete; attached after composition so it cannot be skipped |
| 9 | **Referral to extension officers or laboratories** | `services/triage.py` (8 escalation rules), `kb/referral_and_ipdm.md` | `triage` block in `/detect` and `/risk` responses | Complete |
| 10 | **Follow-up monitoring** | `models.FollowUp`, `routers/followup.py` | `GET /followups?due_only=true`, `PATCH /followups/{id}` | Complete; a failed outcome auto-escalates the case |
| 11 | **Learns from field confirmations** | `models.TrainingSample`, `ml/export_feedback.py`, `GET /review/stats/accuracy` | Confirm a case, then run `export_feedback.py` | Loop complete; retraining is a deliberate manual step |
| 12 | **Dashboards for agriculture officials** | `routers/dashboard.py`, `frontend/src/pages/DashboardPage.jsx` | `GET /dashboard/summary`, `/trend`, `/cases` (each with `include_demo` to separate real from seeded demo data) | Complete; a live-only / demo switch drives every panel |

## Expected outcomes → what produces them

| Outcome in the PS | Mechanism | Where it is measurable |
|---|---|---|
| **Earlier detection** | Risk forecast fires *before* symptoms - a Smith Period is an infection event, not a visible one | `POST /risk` with no image; `by_risk_level` on the dashboard |
| **Reduced crop loss** | Preventive protectant timing + follow-up tracking of whether treatment worked | `GET /followups/stats` → `improvement_rate` |
| **More targeted pesticide use** | Advisory withholds doses on low confidence; healthy crop is told not to spray; repeated failure routes to a lab instead of a third spray; thresholds (15 DSV, 20 moths/trap) gate action | `chemical.status` field; triage codes `low_confidence`, `treatment_failure` |
| **Faster extension response** | Review queue orders escalated and low-confidence cases first; hotspot map shows where to send staff | `GET /review/queue`, `GET /hotspots` |
| **Improved surveillance coverage** | Every photo becomes a georeferenced case; trap ingestion adds a second signal stream | `GET /dashboard/summary` → `cases.total`, `active_sensor_devices` |
| **Better preventive planning** | District-level trend and high-risk district ranking | `GET /dashboard/trend`, `high_risk_districts` |

## Deliberate limitations

Stating these is part of the design, not an omission:

1. **One crop, three classes.** Potato only. The architecture generalises; the model does
   not pretend to.
2. **No XGBoost risk model shipped.** No labelled Indian outbreak dataset exists to train
   one honestly. The training script is written and refuses to produce a model from
   insufficient data, and `scripts/export_risk_dataset.py` builds the dataset from
   expert-confirmed cases as they accumulate - so this is a milestone, not a permanent
   gap. The agronomic models carry the forecasting on their own meanwhile.
3. **PlantVillage is lab imagery.** Every metric from a PlantVillage-only run is a LAB
   metric. `ml/prepare_dataset.py` warns when the val split has zero field images, and
   `ml/evaluate.py` reports lab and field mAP separately and refuses to present a lab
   number as field accuracy. Merging real field-condition images is the single
   highest-value outstanding task on this project.
4. **Doses need local validation.** Every KB file is marked
   `review_status: needs_local_validation` and every advisory repeats it.
5. **No authentication.** Officer endpoints are open in this build. A real deployment
   needs role-based access before the review queue is exposed.
6. **Weather history is cached, not backfilled.** Free-tier OpenWeatherMap has no history
   API, so the Smith Period looks back over our own accumulating cache and is transparent
   about how much of the window is synthetic.
