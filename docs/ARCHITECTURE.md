# Architecture notes

Design decisions and their reasons. The README covers *what* the system does; this
covers *why it is built this way*, which is what a reviewer or a new contributor needs.

## The spine: `Case`

`Case` is the single record everything hangs off. A case is created by `/detect` (a
photo) or `/risk` (proactive, no photo), and it accumulates:

- the detection result (class, confidence, boxes, model version),
- the risk assessment at that moment,
- the triage decision and its reasons,
- the advisory that was issued,
- the expert's verdict,
- follow-up outcomes.

That shape is what makes the harder requirements possible rather than bolted on:

- **"Learns from field confirmations"** - a reviewed case with a label *is* a training
  sample; `TrainingSample` is written on review.
- **"Geospatial hotspot mapping"** - cases carry `geo_cell`, so aggregation is an
  indexed `GROUP BY`, not a clustering job.
- **"Local pest history"** as a risk input - confirmed nearby cases are just a query
  against the same table.
- **Treatment-failure escalation** - follow-up outcomes join back to the farmer's phone
  number, so the system knows a spray has already failed twice.

`Case.effective_class` returns `confirmed_class or predicted_class`: an expert's word
beats the model's, everywhere, without every call site remembering to check.

## Why a geo *grid* rather than clustering

Hotspots use a fixed 0.05° lat/lon grid (~5.5 km) instead of DBSCAN or similar:

- **Stable identity.** A cell keeps its identity as cases accumulate, so an officer can
  watch one square get worse week over week. Cluster IDs from a re-run are not
  comparable.
- **Cheap.** It is an indexed string column and a `GROUP BY`.
- **Explainable.** "This 5 km square has 14 confirmed late blight cases" is a sentence
  an agriculture officer can act on and argue with.

Confirmed cases weigh 1.0, unreviewed predictions 0.4, and the two counts are always
reported separately - officials should not deploy staff on unverified model output, but
they should not be blind to a spike of pending reports either.

The map renders the same data two ways. The grid above is the explainable view. On top of
it, `GET /hotspots/points` returns each case at its own coordinate with that same weight,
and a vendored Leaflet canvas heat layer paints a smooth density surface from those
points. The heatmap localises to village clusters instead of snapping to a 5 km square,
while the grid stays available for the cell-by-cell reading an officer can argue with. The
heat ramp's top of scale is pinned to the "severe" band, so red means the same on both.

Both the map and the dashboard carry a **data-source switch**. Seeded demo rows (marked
`model_version = "demo-seed"` by `scripts/seed_demo_data.py`) exist only so a fresh clone
has something to show. **Live only** filters them out of every panel and the map so an
officer sees exactly what the real field reports say - deliberately very little early on -
while **Demo + live** keeps a walkthrough populated. The filter is written as
`model_version IS NULL OR model_version != 'demo-seed'`, so a real case whose model version
was never recorded is never dropped by it.

## Why triage is its own module

`services/triage.py` sits between the model and the advisory and answers one question:
*is this safe to self-treat?* It is separate from both because:

- It must be **testable in isolation** - it is the safety gate, and every branch has a
  test (`tests/test_triage.py`).
- It must apply **regardless of entry point**. `/detect` and `/risk` both call it through
  `services/pipeline.py`, so a proactive alert cannot bypass a rule a photo case obeys.
- Its output is **structured, not prose** - codes, messages and actions, so the frontend
  can render it and the officer dashboard can count it.

The rules are conservative on purpose. When the system is unsure, it says so and hands
the case to a human rather than naming a pesticide.

## Why the advisory is composed, not generated

An advisory that names a chemical and a dose is a safety-critical output. So:

1. **Doses are parsed from markdown tables** in `data/kb/*.md` (`advisory.parse_dose_table`).
   A human edits that file; a model never writes a number.
2. **Every advisory returns its citations** - which KB sections it drew from, with
   scores and source attributions.
3. **The safety block is attached in a separate graph node** *after* composition, so no
   composition path can accidentally omit it.
4. **The LLM, when configured, writes nothing safety-critical** - only the plain-language
   summary line and translations of free-text excerpts, and translation failures fall
   back to English rather than risk a mistranslated dose.

The pipeline is a LangGraph `retrieve → compose → safety → localize`, with a sequential
fallback if `langgraph` is not installed. The graph is the real implementation; the
fallback keeps a demo machine working.

## Why retrieval has two backends

ChromaDB is the stack default, but its default embedding function downloads a model - 
awkward on a disk-constrained laptop and a hard failure if the download breaks mid-demo.
So `knowledge_base.py` tries Chroma and falls back to a pure-Python BM25 index over the
same chunks. Retrieval quality is reported in `/advisory/status` and on the health
banner, so the fallback is visible rather than silent.

Chunks are split on markdown headings, because "Chemical management" should come back
whole - table and all - rather than sliced mid-row by a fixed-size chunker.

## Why weather is cached in our own table

The agronomic models need an *hourly series over consecutive days*. Free-tier
OpenWeatherMap gives current conditions and a 5-day/3-hour forecast, but **no history**.
So:

- Observed hours are written to `weather_observations` as the system runs, building the
  history the Smith Period needs.
- The 3-hourly forecast is interpolated to hourly, because the models count *hours* above
  a threshold and a 3-hourly series would under-count.
- Any gap is filled from a **deterministic synthetic generator**, and the response says
  exactly how many hours were real: *"38 of 240 hours came from real observations."*

Determinism matters: the same location and date always produce the same synthetic
weather, so demos are reproducible and `test_risk_is_deterministic_for_a_location` can
assert it.

## Why the secondary ML layer is capped

`risk_secondary.py` can move the rule-based score by at most ±0.20, and reports when it
hit that cap. A model trained on a few hundred surveillance rows must not be able to
override a fired Smith Period - a 70-year-old validated criterion outranks a thin fit.
The cap makes that a property of the code rather than a hope.

## Why the live scanner does not trust a single frame

A real-time scanner is the most dangerous surface in this system, because it produces
answers continuously and invites acting on whichever one is on screen. Three properties
make it safe enough to ship:

**Quality gating before inference, not after.** Frames are scored for blur and exposure
first, and unusable ones never reach the model. Running inference on a motion-blurred
frame and then reporting the result is how you get a confident wrong answer - the model
has no way to signal "I could not see that properly", so the caller has to.

**Consensus over a window, not per-frame output.** `stabilizer.js` holds a rolling window
of good frames and offers a verdict only when one class holds a supermajority *and* mean
confidence clears the bar. This directly prevents the failure where one anomalous frame
flashes a disease verdict at a farmer standing over a healthy plant. Poor-quality frames
are recorded for the hint but never dilute or corrupt the consensus.

**Nothing persists without an explicit human action.** Scanning writes nothing - no case,
no advisory, no image on disk (`/detect/frame` deletes the frame it just read). Only
Accept creates a record, and it does so through the *same* `/detect` pipeline as a photo
upload, so an accepted scan gets the identical triage and safety gating. There is no
second, weaker path into the case table.

**Two decoders, one behaviour.** The browser decodes YOLO output in JavaScript while the
server does it in Python. That duplication is a liability, so `yoloDecode.test.js` mirrors
`test_detector.py` case for case with the same numeric expectations, and one test runs a
real ONNX model through onnxruntime-web to confirm both produce the same box. The Python
decoder has already had two genuine bugs (a squeeze that collapsed the anchor axis, and an
ambiguous output orientation); the JavaScript one gets the same scrutiny.

## Degraded versus by-design

`GET /meta/health` returns two separate lists and the frontend renders them differently:

* **`degraded`** - something that should be working and is not: no trained detector, no
  weather API key. These raise a visible banner, because a number derived from synthetic
  weather is not a measurement.
* **`by_design`** - a documented, deliberate state: template-only advisories (the
  intended default, so a farmer needs no API key) and an inactive XGBoost layer (the
  brief's own scoping - rules first, ML only when real data exists). These are collapsed
  behind a disclosure.

Conflating the two misleads in both directions. It implies the system is broken when it is
behaving exactly as specified, and it buries the things that genuinely need fixing in a
list of non-problems. Every entry in either list carries a `remedy` string, so the reader
is never told about a problem without being told what to do about it.

## Why Marathi does not need an API key

The advisory is assembled from a message catalog with `en`/`mr`/`hi`/`bn` entries rather than
translated after the fact. A rural deployment may have no reliable connectivity and no
per-request budget, and a translation API failure must not degrade a farmer's advisory to
English. The catalog also lets an agronomist fix a Marathi term directly, which
machine translation does not.

`GET /meta/languages` reports per-language catalog coverage, so gaps are visible instead
of silently falling back.

Bengali was added the same way - 49 messages, plus class and threat names. The catalog is
now guarded by `test_translations.py`, which checks script per language, placeholder
preservation, and that no entry duplicates another entry's text. That last check exists
because exactly that bug occurred: a regex-based edit spliced one entry's Bengali into
another, and `diag.detected` began returning the word for "low" while every test passed.
Structural checks on translated content are not optional when the content includes
pesticide safety instructions.

## Degradation is a first-class feature

`GET /meta/health` enumerates degraded components, and the frontend renders a permanent
banner explaining each one. A judge, an officer, or a teammate should never have to guess
whether a number came from a real model or a fallback. The alternative - quietly
returning plausible-looking output - is how a demo becomes misleading.

## What is deliberately not built

- **Authentication.** Officer endpoints are open. A real deployment needs role-based
  access before the review queue is exposed.
- **Automatic retraining.** `export_feedback.py` is manual and warns on small or
  district-skewed batches. Retraining on unexamined field data is how a model quietly
  degrades.
- **More crops.** See the scope section of the README.
