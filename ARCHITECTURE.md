# CropGuard — Architecture

A map of the whole system, weighted toward the **mobile app**. **§1 is the one
architecture diagram** — everything is in it. The sections after it are the
detail behind each box, as text and tables.

* **Why** things are built this way → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* **Mobile implementation detail** → [mobileapp/mobileapp.md](mobileapp/mobileapp.md)
* **Product framing** → [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md), [README.md](README.md)

---

## 0. One paragraph

CropGuard is a potato crop disease and pest system for Maharashtra farmers and
agriculture officers. It ships as **two deployments of one codebase**:

| | **Web deployment** | **Mobile deployment** |
|---|---|---|
| Who | Agriculture officers (desk work, maps, review queue) | Farmers (in the field) |
| UI | React (Vite) in a browser | The *same* React bundle, inside an Android WebView |
| Backend | FastAPI + SQLite/Postgres, on a server | **Ported to Dart, running on the handset** |
| Inference | ONNX Runtime (CPU), server-side | onnxruntime-web (WASM), **in the WebView** |
| Network | Required | Required **once**, then fully offline |

The shared seam is the HTTP API. The React UI issues the same `fetch('/api/...')`
calls in both worlds; only the thing answering them changes.

---

## 1. The architecture diagram

```text
┌─ BUILD & RELEASE ────────────────────────────────────────────┐            ┌─ CLOUD ──────────────────────────────────────┐
│ [N18] ML TRAINING — Kaggle GPU, Ultralytics YOLOv8           │            │ [N12] STATIC BUCKET (HTTPS, no server)       │
│   ml/ potato · croprow/ lettuce · croprow_disease/ health    │            │                                              │
│   prepare → train → tune_thresholds → export_onnx            │            │ packs/index.json       catalogue (tiny)      │
│   → build_pack.py (UTF-8, LF always)                         │─ packs ──► │ packs/<crop>/<ver>/                          │
│                                                              │ verify_pub-│   manifest.json        SHA-256 per file,     │
│ frontend/ ── stage_web.ps1 ──► app/assets/web/               │ lished_    │                        min_app_version       │
│ export_demo_dataset.py ──────► app/assets/demo/              │ packs.py   │   model.onnx           weights               │
│ flutter build apk ───────────► cropguard.apk                 │            │   thresholds.json      tuned for weights     │
│                                                              │─ apk ────► │   taxonomy.json        class order           │
│ [N19] GOLDEN FIXTURES  mobileapp/fixtures/*.json             │            │   strings.json         4 languages           │
│   Python services ⇄ Dart port, 108 cases                     │            │   kb/*.md              advisory pages        │
│   export_fixtures.py --check  (CI)                           │            │ cropguard.apk (54 MB) + index.html           │
└──────────────────────────────────────────────────────────────┘            └──────────────────────────────────────────────┘
                                                                              ║ ① first launch only: index.json, then the pack
                                                                              ▼
┌─ ANDROID HANDSET — one process · online only at ① · in.cropguard.cropguard ──────────────────────────────────────────────┐
│ [N1] FLUTTER SHELL  main.dart                                                                                            │
│   BOOT  ② start LocalServer ─► ③ crop pack active? ─ no ─► [N2] CROP PICKER ═①═► [N12] (skippable)                       │
│         ④ camera permission ─► ⑤ load WebView at http://127.0.0.1:<port>                                                 │
│         (③ must precede ⑤: the page reads /detect/status once at startup)                                                │
│   also  file-chooser bridge · console → logcat · Back walks WebView history · error/loading panes                        │
│                                                                                                                          │
│ ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ [N3] WEBVIEW — the SAME React bundle as the web app (10 pages, en · mr · hi · bn)                                    │ │
│ │   detectPhoto.js ── GET /detect/status ── inference:"in_page" → infer here, not upload                               │ │
│ │   [N4] onnxruntime-web (WASM) — photo AND live scan; weights from GET /api/detect/model                              │ │
│ │        live scan: blur/exposure filter + 6-of-10 frame consensus before a verdict                                    │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                    │ fetch("/api/…") + detections                ▲ JSON, server-identical shape                          │
│                    ▼                                             │                                                       │
│ ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ [N5] LOCAL SERVER  local_server.dart — dart:io HttpServer on 127.0.0.1:<OS-assigned port>                            │ │
│ │   / , /assets/*  → read from APK (Cache-Control: immutable)                                                          │ │
│ │   /api  meta · risk · detect · croprow · crophealth · advisory · packs · officer views · chat                        │ │
│ │   POST /detect → 503 by design (inference is in-page)    unmatched /api → 503 + reason                               │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│           │                      │                     │                        │                                        │
│           ▼                      ▼                     ▼                        ▼                                        │
│ [N6] DOMAIN            [N7] KB / ADVISORY     [N8] PACK STORE           [N10] DEMO API                                   │
│ weather: synthetic,    BM25 over pack         catalog → manifest →      demo_api.dart derives                            │
│   SHA-256 seeded       kb/*.md sections       download → verify →       dashboard, hotspots,                             │
│ risk: Smith ·          retrieve → compose     install (atomic swap)     review queue, stats                              │
│   Beaumont · TOMCAST   → safety → localize    POST /install → 202,      when include_demo=true;                          │
│   · degree-days        doses PARSED from      poll /packs/progress      else empty payloads                              │
│ triage: 8 rules        markdown, never        only CROP packs can       with every key kept                              │
│ taxonomy · geo cells   generated              be "active"                                                                │
│                        follow-up date         refuses bad SHA-256,                                                       │
│                                               version, rollback                                                          │
│                                                                                                                          │
│ FARMER LOOP (all offline):                                                                                               │
│   weather risk ─► photo / live scan ─► TRIAGE ─┬─► advisory + doses ─► follow-up scheduled                               │
│                                                └─► escalate to expert / lab — no pesticide advised                       │
│                                                                                                                          │
│ ┌─ ON-DEVICE STORAGE ──────────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ [N9]  <documents>/packs/<crop>/<ver>/   installed packs — never the cache dir (Android evicts it)                    │ │
│ │ [N11] assets/web/    UI bundle + ORT wasm ×2          assets/demo/dataset.json  120 cases · 520 traps                │ │
│ │ ✗ no local case DB yet — nothing a farmer records persists                                                           │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
          ┊
          ┊ [N20] sync worker / outbox — NOT BUILT: would upload cases and pull cross-farm digests
          ┊
┌─ WEB DEPLOYMENT — officers ──────────────────────────────────────────────────────────────┐     ┌─ EXTERNAL ─────────────┐
│ [N13] React UI (browser) ── REST /api ──► [N14] FastAPI  backend/app/main.py             │ ──► │ [N16] OpenWeatherMap   │
│   routers: meta detect risk advisory home hotspots review followup                       │     │       forecast         │
│            sensors dashboard chat croprow crophealth                                     │     │                        │
│   services/pipeline.py — the same core loop:                                             │ ──► │ [N17] Gemini           │
│     image? → detection ─┐                                                                │     │       chat assistant   │
│     location → weather ─┴→ risk → TRIAGE → advisory (RAG) → Case + FollowUp              │     └────────────────────────┘
│   ONNX Runtime (CPU) · LangGraph · ChromaDB + BM25 · XGBoost ±0.20 cap                   │
│         │ SQLAlchemy                                                                     │
│         ▼                                                                                │
│ [N15] SQLite / Postgres                                                                  │
│   Case ─1:N─► FollowUp       (2 failed → triage: suspect resistance)                     │
│   Case ─1:N─► TrainingSample (officer-confirmed label)                                   │
│   SensorReading · WeatherObservation (own cache)                                         │
│   TrainingSample ── ml/export_feedback.py ──► back to [N18] retraining                   │
└──────────────────────────────────────────────────────────────────────────────────────────┘

  ①–⑤ boot order     ═══ network edge     ┊ not built yet
  ✗ THERE IS NO EDGE BETWEEN THE HANDSET AND [N14] FastAPI. The phone never calls the backend;
    its only network edge is ① — crop packs from the static bucket, once.
```

**No edge exists between the handset and the FastAPI backend.** That is the
central architectural fact: the mobile app does not call the server at all. It
calls its own in-process server. The only mobile↔network edge (①) goes to a dumb
static bucket, and only to fetch crop packs.

---
## 2. Mobile app — the four layers

One Android process (`in.cropguard.cropguard`), four layers, ~5,000 lines of Dart.

| Layer | File | Role |
|---|---|---|
| **L1 Flutter shell** | `app/lib/main.dart` (399 ln) | Hosts the WebView; camera permission at boot; file-chooser bridge; Back → WebView history; console → logcat; boot/loading/error panes; first-launch crop picker (the one online screen) |
| **L2 WebView** | bundled `assets/web/` | The same React UI as the web deployment, served from `http://127.0.0.1:<port>`; onnxruntime-web runs photo **and** live inference in-page |
| **L3 Local server** | `app/lib/local_server.dart` (1200 ln) | `dart:io` HttpServer on `127.0.0.1:0`; serves `assets/web/*` from the APK (`Cache-Control: immutable`); implements the whole `/api` surface; one `switch` in `_api()`; unmatched → 503 with a real reason |
| **L4 Dart domain** | `app/lib/{domain,kb,packs,demo}` | Risk models, triage, taxonomy, geo, weather · BM25 + advisory · pack download/verify/install · demo dataset |

The only network hop is L1's crop picker → static bucket over HTTPS, on first launch, and it is skippable.

### Layer 4 file map

| File | Lines | Responsibility |
|---|---|---|
| `domain/weather.dart` | 222 | Deterministic synthetic weather (SHA-256 seeded) |
| `domain/risk_models.dart` | 390 | Smith Period, Beaumont Period, TOMCAST DSV, degree-days |
| `domain/triage.dart` | 213 | The 8-rule safety gate |
| `domain/taxonomy.dart` | 129 | Classes, threat keys, 4-language names |
| `domain/geo.dart` | 62 | Hotspot cell maths |
| `domain/num_compat.dart` | 59 | Python-compatible number formatting |
| `kb/knowledge_base.dart` | 330 | BM25 retriever over pack KB pages |
| `kb/advisory.dart` | 353 | Advisory composer: actions, doses, safety, follow-up |
| `packs/pack.dart` | 177 | Pack / manifest model |
| `packs/pack_store.dart` | 451 | Download, verify, atomic install, active-pack rules |
| `packs/crop_picker.dart` | 258 | First-launch crop selection |
| `demo/demo_dataset.dart` | 339 | Loads and materialises the demo asset |
| `demo/demo_api.dart` | 440 | Derives dashboards, hotspots, queues from demo rows |

---

## 3. Boot sequence (ordered — the order is load-bearing)

1. `main()`
2. `LocalServer.instance.start()` binds `127.0.0.1:0` — the OS picks a free port, so a fixed port cannot collide with anything else on the phone.
3. `PackStore.instance.activePack()` — is a crop pack installed?
   * **No →** show the **crop picker** (the one online screen): `GET <bucket>/packs/index.json`, farmer picks a crop, 45 MB download. **Skippable** — risk forecasting works with no pack.
4. `Permission.camera.request()` — asked at boot with context, not mid-scan by the WebView.
5. `controller.loadRequest(origin)` — the WebView loads `http://127.0.0.1:<port>`.
6. The page calls `GET /api/detect/status` **once** at startup — which is why step 3 must happen **before** step 5: a pack installed after load leaves the scanner convinced there is no detector.

Failure at step 2 renders `_ErrorPane` — *"CropGuard could not start"* — which
states explicitly that this is **not** a network problem.

---
## 4. Where inference runs — the one seam

`frontend/src/lib/detectPhoto.js` is the **only** file that differs in behaviour
between the two deployments, and it branches on a capability flag, not a build
target.

1. Farmer taps **Check crop** and picks a photo.
2. `detectPhoto.js` calls `GET /api/detect/status`.
3. **Server build** (no `inference` key) → `POST /api/detect` uploads the photo, unchanged; the server runs ONNX.
4. **Handset build** (`inference: "in_page"`) →
   1. decode the image with `createImageBitmap` (falls back to `<img>` on old WebViews);
   2. build the `LiveDetector` session once and cache it (weights are tens of MB);
   3. `GET /api/detect/model` — weights read straight off disk from the pack;
   4. POST the detections back to the **local** API for the triage gate, advisory + doses and risk forecast — all offline.
5. Same response shape either way.

**Only the pixels needed the page.** Everything judgemental stays in the ported
domain code, so phone and server reach the same verdict from the same detections.

Two consequences worth knowing:

* **There is no ONNX runtime in the Dart process.** The runtime already existed
  in the WebView for the live scanner; the photo path reuses it.
* **`POST /api/detect` on the handset returns 503 *by design*** — with a message
  naming which crop to install, and stating *"This is not a network problem."*

### Honest absence

With no model installed, `detectPhoto` still returns a **full** response: no
class, no confidence, but a triage verdict, an escalation route and a note
explaining why there is no diagnosis. Cases route to the expert queue rather
than returning a confident wrong label.

---

## 5. Request lifecycle inside the handset

| Request from the WebView | LocalServer handles it with | Backed by |
|---|---|---|
| `GET /`, `GET /assets/*` | `rootBundle`, `Cache-Control: immutable` | APK `assets/web/` |
| `GET /api/...` (risk, triage, meta) | `_api()` switch → `domain/` | computed |
| `GET/POST /api/advisory*` | `_api()` → `kb/` | BM25 over the pack's KB pages |
| `/api/packs/*` | `_api()` → `packs/` | `<documents>/packs/` |
| officer views | `_api()` → `demo/` | bundled `dataset.json` |
| `GET /api/detect/model` | streams `model.onnx` (tens of MB) | `<documents>/packs/potato/1.0.1/` |
| anything unmatched | 503 + reason | — |

onnxruntime-web then runs the streamed model in-page.

A missing static file is answered with `index.html` (SPA routing), so a genuinely
absent asset surfaces as a **MIME type error, not a 404** — recorded here because
it costs debugging time.

---
## 6. Crop packs — a crop is a download, not an app release

**No model weights ship in the APK.** Every crop, including potato, is
downloaded. One code path, exercised from the very first launch.

### Bucket / on-disk layout

| Path under `<base>/packs/` | Contents |
|---|---|
| `index.json` | The catalogue — a few hundred bytes |
| `potato/1.0.1/manifest.json` | Per-file SHA-256, `min_app_version` |
| `potato/1.0.1/model.onnx` | The weights |
| `potato/1.0.1/thresholds.json` | Tuned **for** those weights |
| `potato/1.0.1/taxonomy.json` | Class list, in model index order |
| `potato/1.0.1/strings.json` | Class names + advisory text, 4 languages |
| `potato/1.0.1/kb/*.md` | The pages the advisory is built from |

The phone fetches `index.json` **first** — a few hundred bytes before deciding
whether to pull 45 MB, which matters on a metered rural connection.

### Published today

| Pack | Kind | Version | Size | Classes |
|---|---|---|---|---|
| `potato` | **crop** | 1.0.1 | ~45 MB | `potato_early_blight`, `potato_late_blight`, `potato_healthy` |
| `croprow` | **detector** | 1.0.0 | ~11 MB | `lettuce` |
| `crophealth` | **detector** | 1.0.0 | ~11 MB | `healthy`, `unhealthy` |

### Two kinds of pack — the distinction is load-bearing

| | `crop` | `detector` |
|---|---|---|
| Contents | model, thresholds, taxonomy, strings, **KB pages** | model, thresholds, taxonomy |
| Drives | photo diagnosis → triage → treatment advice | one lab scanner |
| Can be "active"? | **yes** | **never** |

`activePack()` considers **crop packs only**. Without that rule, installing
"Crop row scan" would repoint the potato scanner at a single-class lettuce
localiser and return boxes labelled "lettuce" with no error anywhere.

A crop pack without KB pages is a bug — it could diagnose and never advise.
A detector pack without them is *correct*: a box drawn around a lettuce is not
advice and must not be dressed up as any.

### Install pipeline — download, verify, **then** swap

`POST /api/packs/install` returns **202** immediately and runs the transfer in
the background (**409** + in-flight progress if one is already running; **400**
on a bad body, checked *before* the 409). Phases, in order:

1. `catalog` → 2. `manifest` → 3. `download` (staged in a temp dir) →
4. `verify` → 5. `install` (atomic move into `<documents>/packs/` — **never** the
cache dir, which Android evicts) → 6. `done`

The UI polls `GET /api/packs/progress` for
`{active, phase, received_bytes, total_bytes, file}`.

**A pack that fails any check leaves nothing behind.** The payload is a table of
pesticide doses; TLS protects the transport, not a compromised bucket or a wrong
upload.

| The installer refuses | |
|---|---|
| A file whose bytes fail its SHA-256 | installs nothing |
| A truncated body | installs nothing |
| Manifest describing a different crop/version than the catalogue offered | *"Refusing to install."* |
| `min_app_version` above this build (`kAppVersion = 1.0.0`) | *"Update the app first."* |
| Version ordering is numeric, not lexical | `1.0.10` > `1.0.9` |
| Rollback to an older version | rolls back rather than keeping the newer |
| An unparseable manifest already on disk | left for forensics, never half-served |

> **Signing is scaffolded, not enforced.** `manifest.signature` exists and
> `PackStore.install` checks it, but `allowUnsigned` defaults to `true` and
> `build_pack.py` writes `"signature": null`. **SHA-256 per file is the real
> integrity control today.**

### Catalogue URL is runtime-configurable

Menu → Crop models → *Where crops are downloaded from*, stored in
`<documents>/packs/catalog_url`, surviving app updates; also
`GET|POST /api/packs/source`. A build-time-only constant would mean a handset
pointed at a host that later disappears can never be recovered without
reinstalling — not something you can ask a farmer to do.

Build-time default: `--dart-define=PACK_CATALOG_BASE=https://<bucket>/packs`.
The compiled fallback `https://packs.cropguard.in/packs` **does not exist yet**.

---
## 7. What is offline, what needs a network

The rule throughout: **state the absence, never fabricate the data.**

* **Airplane mode — fully working:** weather feed · risk models · geo/hotspot
  cells · triage gate · taxonomy · photo diagnosis · live scanner · lab scanners ·
  advisory (BM25 RAG) · dose tables · follow-up scheduling · officer screens on demo data.
* **Needs a connection:** pack catalogue + download (once) · cross-farm outbreak
  pressure, officer dashboard, review queue (by definition these live on other
  people's devices) · chat assistant.
* **Not built yet:** real weather prefetch · sync/outbox upload · local case persistence.

| Offline capability | Implementation | Held to |
|---|---|---|
| Weather feed | `domain/weather.dart` — synthetic series seeded by SHA-256 of rounded coords + date/hour | matches the server's `_seeded_unit` exactly |
| Risk models | `domain/risk_models.dart` | `fixtures/risk_models.json`, 40 cases |
| Geo / hotspot cells | `domain/geo.dart` | `fixtures/geo.json`, 18 cases |
| Triage safety gate | `domain/triage.dart` | `fixtures/triage.json`, 25 cases |
| Taxonomy, 4 languages | `domain/taxonomy.dart` | `offline_engine_test.dart` |
| Photo + live diagnosis | onnxruntime-web in the WebView, weights from the pack | `pack_store_test.dart` |
| Advisory / RAG | `kb/knowledge_base.dart` + `kb/advisory.dart` | `fixtures/kb.json`, 25 cases |
| Dose tables | **parsed** from reviewed markdown in the pack, never generated | the markdown file itself |
| Officer screens | `demo/demo_api.dart` over the bundled dataset | `export_demo_dataset.py --check` |

### The `include_demo` toggle — two honest answers, farmer's choice

* `include_demo=true` (UI's *"Demo + live"*, the default) → the synthetic dataset
  bundled in the APK.
* `include_demo=false` (*"Live only"*) → genuinely empty results, because this
  device holds no other farmers' cases until it syncs.

**Either way the payload shape is the server's.** The UI reads payloads
positionally (`summary.cases.total`, `rows.find(...)`), so an
`{items: [], offline: true}` envelope is *harder* to fail on than a 500: the read
throws during render, React unmounts the tree, and the farmer gets a white screen
with no way back. Empty payloads therefore carry **every** key the full ones do,
including `unverified_weight` (0.4) and `severe_threshold` (8.0), mirrored from
`backend/app/routers/hotspots.py` so the heat ramp does not silently re-scale the
day sync fills it in.

### `/api/meta/health` reports it rather than hiding it

```json
{ "status": "ok", "mode": "offline", "degraded": [],
  "by_design": [
    {"code": "offline_build",        "detail": "Running fully on-device …"},
    {"code": "detector_not_bundled", "detail": "No image detection model ships in this build …"}
  ] }
```

`degraded` stays **empty** because none of this is a fault. Everything absent is
in `by_design`, with a reason string the UI can show.

---

## 8. The on-device API surface

All served by `local_server.dart` at `http://127.0.0.1:<port>/api`.
**O** = fully offline · **N** = needs a network · **D** = demo-backed (empty when `include_demo=false`)

| Group | Route | | Notes |
|---|---|---|---|
| **Meta** | `GET /meta/health` | O | `mode: offline`, `degraded: []`, `by_design: [...]` |
| | `GET /meta/classes` | O | crop, class list, `non_model_threats` |
| | `GET /meta/languages` | O | en · mr (मराठी) · hi (हिन्दी) · bn (বাংলা) |
| **Risk** | `GET /home/overview` | O | defaults to 18.52, 73.86 (Pune) |
| | `POST /risk` · `GET /risk` | O | coords from body or query |
| | `GET /risk/weather` | O | deterministic synthetic series |
| | `GET /risk/models` | O | Smith (1956); Beaumont (1947); TOMCAST; degree-days — each with citation |
| **Detection** | `GET /detect/status` | O | `model_available`, **`inference: "in_page"`** |
| | `GET /detect/model` | O | the weights, straight off disk |
| | `GET /detect/thresholds` | O | per-class cut-offs from the pack |
| | `POST /detect`, `/detect/frame` | — | **503 by design** — names the crop to install |
| | `GET /croprow/status`, `/crophealth/status` | O | returns `available` (not `model_available` — the server's shape) |
| | `GET /croprow/model`, `/crophealth/model` | O | detector weights |
| | `GET /croprow/thresholds`, `/crophealth/thresholds` | O | |
| **Advisory** | `GET /advisory/status` | O | `backend: "lexical-bm25"`, doc/chunk counts, active pack |
| | `GET /advisory/search` | O | BM25 over the pack's KB pages |
| | `POST /advisory` | O | actions, doses, safety bullets, follow-up date |
| **Packs** | `GET /packs/installed` | O | each with `kind`, `classes`, `active` |
| | `GET /packs/catalog` | **N** | the one call that genuinely needs a connection |
| | `GET\|POST /packs/source` | O | runtime catalogue URL + `compiled_default` |
| | `POST /packs/install` | **N** | 202 + background; 400 bad body; 409 if one running |
| | `GET /packs/progress` | O | poll target |
| **Officer** | `GET /hotspots` | D | keys preserved: `window_days`, `cell_size_deg`, `unverified_weight`, `total_*`, `cells` |
| | `GET /hotspots/points` | D | + `severe_threshold: 8.0` |
| | `GET /review/queue` | D | JSON **array** (`list[CaseOut]` on the server) |
| | `GET /followups`, `/sensors` | D | JSON arrays |
| | `GET /dashboard/summary`, `/trend`, `/districts` | D | |
| | `GET /review/stats/accuracy` | D | |
| | `GET /followups/stats`, `/sensors/summary` | D | |
| | `GET /dashboard/cases` | — | always `[]` |
| | `GET /chat/status` | — | `mode: "offline"` + what still works |

**Anything unmatched → 503**, *"This feature needs a network connection and is
not available in the offline build."* Never a fake 200.

---
## 9. The farmer loop

The whole loop runs on the handset with the radio off.

1. **Weather risk forecast** — works with no image at all.
2. **Photo or live scan** → detections.
3. **Triage** (`domain/triage.dart`) — every case goes through one gate; a weather
   alert can never bypass a rule a photo case obeys.
4. Cleared → **advisory (RAG)**: retrieve → compose → safety → localize.
   Escalated → **route to an expert / lab** instead of recommending a pesticide.
5. **Doses + follow-up date** scheduled (`kFollowUpDays`).

### The triage gate — 8 rules, in order

| # | Rule | Behaviour |
|---|---|---|
| 1 | No model available | No diagnosis. Never guess a pesticide from nothing. |
| 2 | Model ran, saw nothing above threshold | `no_detection` |
| 3 | Confidence below threshold | `low_confidence` — **the core safety rule**; `self_treatment_allowed = false` |
| 4 | Image and weather disagree | `conflicting_signals` — the classic misdiagnosis trap |
| 5 | High weather risk + healthy-looking crop | a **preventive window**, not an alarm |
| 6 | ≥2 failed treatments | `resistance` — refer to a lab, not a bigger dose |
| 7 | Severity ≥ 25% of field | `high_severity` — an outbreak, not an individual problem |
| 8 | Confident high-severity disease | urgent even if self-treatable |

> **Two safety questions on the record** (judgement calls, recorded rather than
> quietly changed):
> 1. `conflicting_signals` escalates but still leaves `self_treatment_allowed = true`,
>    while the weaker `low_confidence` sets it `false`.
> 2. `high_severity` escalates to district at `urgent` but also leaves
>    `self_treatment_allowed` true — arguably right, but it should be a decision,
>    not a consequence of rule 7 not setting the flag.

### Offline advisory (RAG)

1. Query = class key + field terms.
2. `kb/knowledge_base.dart` — BM25 over the pack's KB markdown pages, chunked by
   section. The index is rebuilt only when the active pack changes (keyed on
   `crop@version`).
3. `kb/advisory.dart` — retrieve → compose → safety → localize, as four plain
   function calls.
4. Output: actions · **doses** · safety bullets · follow-up date.

**There is no vector backend and no embedding model — BM25 is the
implementation, not a fallback.** An honest fit: the corpus is six markdown
pages, the query is a class key plus a few field terms, the retrieval unit is a
markdown section. The server runs the same four steps as a LangGraph pipeline;
a graph runtime buys orchestration a handset does not need.

**Nothing generative is ported, because nothing generative exists.** Doses are
*parsed* out of reviewed markdown tables on the server too. The numbers a farmer
sprays by stay accountable to a file an agronomist can correct in a pull request
— which matters **more** on a handset, not less, because there is nobody there
to catch a hallucinated dose.

---

## 10. Demo data on the handset

`app/assets/demo/dataset.json` — 293 KB, seed 2026, 90-day window:
**120 cases · 120 follow-ups · 520 trap readings** across Maharashtra potato
districts. The app derives the dashboard, hotspot cells, review queue and
follow-up statistics from those rows, so the period selector and district filter
genuinely filter rather than moving four fixed numbers.

* **Records store day offsets, not timestamps**, materialised against the clock
  when the asset loads — an APK built in September must not show September cases
  at Christmas with an empty "last 7 days" window.
* **Never passed off as real**: every record carries `demo: true`, farmer names
  start "Demo", model version is `demo-seed`.
* Parsed once and held in memory — re-parsing 293 KB per request would be
  visible on a cheap handset.

Sibling of `scripts/seed_demo_data.py` (which seeds the *server's* SQLite), not a
replacement. Neither reads the other's output.

---
## 11. Android specifics — each was an invisible failure first

| Concern | Config / code | Failure without it |
|---|---|---|
| **INTERNET permission** | must be in `src/main/AndroidManifest.xml` | Flutter only declares it for debug/profile. A release build **loads nothing, silently** — including the loopback server |
| **Cleartext for loopback only** | `res/xml/network_security_config.xml` permits `127.0.0.1` + `localhost`, with `<base-config cleartextTrafficPermitted="false"/>` | `ERR_CLEARTEXT_NOT_PERMITTED` with no useful message. A blanket `usesCleartextTraffic="true"` would permit unencrypted traffic to *any* server — a real downgrade for an app that will later sync farmer names, phones and plot coordinates |
| **File chooser bridge** | `setOnShowFileSelector(_pickFiles)` in `main.dart` | The WebView asks the host via `onShowFileChooser`; an unanswered request leaves the tap **silently dead** — no picker, no error, nothing in logcat. Affects video upload on both lab scanners and the photo picker on Check crop |
| **Picker narrowing** | handler honours `accept="video/*"` | A farmer picking a still the clip scanner then refuses is worse than no picker |
| **Picker exceptions** | returns an empty list on **any** exception | A picker that throws without returning leaves the input pending; the next tap does nothing either |
| **Camera** | `Permission.camera` at boot; `setMediaPlaybackRequiresUserGesture(false)`; WebView permission granted | Otherwise the WebView's own prompt appears with no context mid-scan, and `getUserMedia` needs a synthetic gesture |
| **Console forwarding** | `setOnConsoleMessage` → logcat | A JS error in the bundled UI is otherwise **completely invisible**: white WebView, `onWebResourceError` silent because the document loaded fine |
| **Back button** | `PopScope(canPop: false)` walks WebView history first | Otherwise Back drops the user out of the app from three screens deep |

Subframe/asset errors are filtered out of the user-facing error pane
(`err.isForMainFrame != true` returns early) — noisy and mostly harmless.

### Build notes

* `flutter_plugin_android_lifecycle` **pinned to 2.0.24** in `dependency_overrides`
  — `file_picker` pulls it in, and 2.0.35 demands API 36 while `file_picker`
  itself compiles against 34.
* `kotlin.incremental=false` — the cache corrupted itself repeatedly (pub cache on
  `C:`, project on `D:`; Kotlin's `File.relativeTo()` throws across drive letters).
* `org.gradle.jvmargs=-Xmx8G` with 4G metaspace — 28 MB of bundled web assets
  makes packaging memory-hungry.

---

## 12. Keeping the Dart port honest

The agronomic models, triage gate, geo maths and retriever were **ported from
Python to Dart**. A port is only as good as its evidence.

`export_fixtures.py --write` runs the Python services in `backend/app/services/`
and records their inputs and outputs as **golden vectors** — language-neutral JSON
in `mobileapp/fixtures/*.json`. `flutter test` asserts the Dart port in
`mobileapp/app/lib/{domain,kb}/` hits the same numbers, and
`export_fixtures.py --check` guards both sides in CI.

| Suite | Cases | Dart test |
|---|---|---|
| `fixtures/geo.json` | 18 | `fixtures_geo_test.dart` |
| `fixtures/kb.json` | 25 | `fixtures_kb_test.dart` |
| `fixtures/risk_models.json` | 40 | `fixtures_risk_models_test.dart` |
| `fixtures/triage.json` | 25 | `fixtures_triage_test.dart` |
| **Total golden cases** | **108** | 0 diffs |

Plus `offline_engine_test.dart` (end-to-end offline behaviour), `pack_store_test.dart`
(install/refusal against a real HTTP server), **`api_contract_test.dart`** (the JSON
*type and keys* of every offline payload — the guard against the white-screen
failure in §7), and `widget_test.dart`.

**Verification commands:**

| Check | Command | Result |
|---|---|---|
| Flutter/Dart tests | `flutter test` (in `mobileapp/app/`) | **163 passed** |
| Golden vectors vs Python | `python mobileapp/tools/export_fixtures.py --check` | **108 cases, 0 diffs** |
| Demo dataset vs generator | `python mobileapp/tools/export_demo_dataset.py --check` | **matches** |
| Published pack bytes | `python mobileapp/tools/verify_published_packs.py` | hashes the **staged git blob** |

Two real differences the fixtures caught: Python's `list.sort` is stable and
Dart's is not (tied BM25 chunks now break ties on corpus index), and the two
languages disagree about number printing at the edges (`domain/num_compat.dart`)
— a dose rendering as `2.5` on one and `2.50000000000000004` on the other is a
support ticket.

A failing `--check` is **read, not regenerated away**.

---

## 13. Build and release pipeline

1. **Web UI:** `frontend/` → `stage_web.ps1` (vite build) → `mobileapp/app/assets/web/`.
2. **Demo data:** `export_demo_dataset.py` → `mobileapp/app/assets/demo/`.
3. **APK:** `flutter build apk --release --dart-define=PACK_CATALOG_BASE=…` →
   `dist/cropguard.apk` (54 MB), `dist/cropguard.apk.sha256`, `dist/index.html` (install page).
4. **Models:** `ml/`, `croprow/`, `croprow_disease/` — YOLOv8 training on Kaggle GPU →
   `export_onnx.py` → `tune_thresholds.py`.
5. **Packs:** `build_pack.py` (UTF-8, LF **always**) → `dist/packs/**` →
   `verify_published_packs.py` → static bucket (S3 / R2 / GitHub Pages).

### What is in the 54 MB

| Component | Size |
|---|---|
| Published APK | 56,098,065 B (53.5 MiB) |
| ├─ ORT wasm runtime **×2** | 27.9 MB |
| ├─ UI bundle (`index-*.js` + `.css`) | ~1.0 MB |
| ├─ demo dataset | 293 KB |
| └─ Flutter engine, Dart AOT, resources | remainder |

**Two ORT copies** ship: the Vite-hashed
`assets/web/assets/ort-wasm-simd-threaded-*.wasm` and the stable-named
`assets/web/ort/ort-wasm-simd-threaded.wasm`. `onnxruntime-web` resolves the
runtime by a path it computes at session creation, and the hashed name alone did
not satisfy every resolution path. That is 14 MB and the single largest trimmable
thing.

> `assets/web/` is **gitignored build output, not source.** Forgetting
> `stage_web.ps1` ships a stale UI, and the mismatch is invisible until someone
> notices a fix missing on the phone. Flutter does not recurse into asset
> subdirectories, so `pubspec.yaml` lists `assets/web/`, `assets/web/assets/`,
> `assets/web/ort/` and `assets/demo/` individually.

### Identity

| | |
|---|---|
| Application ID / namespace | `in.cropguard.cropguard` |
| Label | CropGuard |
| Version | `1.0.0+1` → `versionName 1.0.0`, `versionCode 1` |
| `kAppVersion` (pack gate) | `1.0.0` — keep in step with pubspec |
| Java / Kotlin target | 17 |
| Toolchain | Flutter 3.47.4 · Dart 3.13.3 · Gradle 9.3.1 |

> **Release builds are signed with the debug key.** Fine for handing an APK
> round; **not** fine for a distribution channel, and a properly-signed build
> cannot upgrade an installed debug-signed one.

---
## 14. The web deployment (for contrast)

Officers stay on the React web app: desk work, large screens for maps and
charts, and a review queue that is inherently multi-user.

* **React frontend (Vite)** — 10 routes (`/`, `/scan`, `/check`, `/risk`, `/map`,
  `/dashboard`, `/review`, `/models`, `/croprow`, `/crophealth`), 4 languages,
  Leaflet + Mapbox GL, Recharts. `api.js` calls `VITE_API_BASE || '/api'`.
* ↓ **REST**
* **FastAPI** (`backend/app/main.py`)
  * `routers/`: meta, detect, risk, advisory, home, hotspots, review, followup,
    sensors, dashboard, chat, croprow, crophealth
  * `services/`: pipeline, detector, risk_engine, risk_models, risk_secondary,
    triage, advisory, knowledge_base, weather, geo, taxonomy, translate, chat,
    home_overview, croprow_detector, crophealth_detector
* ↓ **SQLAlchemy**
* **SQLite** (`cropguard.db`) / **Postgres**

**The core loop lives in `backend/app/services/pipeline.py`.** Both `/detect`
(reactive, farmer uploads a photo) and `/risk` (proactive, no image) run through
it — same safety gate, same advisory pipeline, same case record feeding the
hotspot map and the officer dashboard.

1. Image? → **detection**; location → **weather**.
2. Both → **risk assessment** → **TRIAGE**.
3. Cleared → **advisory (RAG)** → persisted **Case + FollowUp**.
4. Escalated → an expert instead of a pesticide recommendation.

Differences from the handset, worth drawing as annotations:

| | Server | Handset |
|---|---|---|
| Inference | ONNX Runtime (CPU), in-process | onnxruntime-web (WASM), in the WebView |
| Advisory orchestration | LangGraph pipeline | four plain function calls |
| Retrieval | ChromaDB + BM25 hybrid | BM25 only |
| Weather | OpenWeatherMap + own cache table | deterministic synthetic feed |
| Risk refinement | XGBoost + TreeSHAP, capped at ±0.20 | not ported |
| Persistence | SQLAlchemy → SQLite/Postgres | **none yet** — demo asset + memory |
| Chat | Gemini server-side | offline stub |

---

## 15. Data model (server-side; the shape the mobile payloads mirror)

| Table | Key fields | Relations |
|---|---|---|
| **Case** — *the spine* | identity: `farmer_name`, `phone` · crop: `crop`, `variety`, `crop_stage`, `soil_condition` · place: `district`, `village`, `latitude`, `longitude`, `geo_cell` · model: `image_path`, `predicted_class`, `confidence`, `detections[]`, `model_version` · risk: `risk_level`, `risk_score`, `risk_detail` · decision: `escalate`, `escalation_reasons[]`, `advisory{}`, `language` · review: `review_status`, `confirmed_class`, `reviewer`, `reviewer_notes`, `reviewed_at` | 1:N FollowUp, 1:N TrainingSample |
| **FollowUp** | `due_date`, `outcome`, `treatment_applied`, `notes`, `closed_at` | N:1 Case. **2× UNCHANGED/WORSENED** → triage rule 6: suspect resistance, refer to a lab |
| **TrainingSample** | `label`, `was_model_correct`, `model_version`, `exported` | N:1 Case. A **confirmed** review becomes a labelled sample |
| **SensorReading** | `device_id`, `device_type`, `metric`, `value`, `geo_cell`, `recorded_at` | standalone |
| **WeatherObservation** | `geo_cell`, `observed_at`, … | standalone (own cache table) |

Hotspots aggregate `Case` rows by `geo_cell` over a rolling window, weighting
confirmed cases above unverified ones (`unverified_weight = 0.4`,
`severe_threshold = 8.0`).

---

## 16. ML pipeline

1. **Datasets** (PlantVillage + field splits, lettuce footage) →
   `ml/prepare_dataset.py`, `merge_field.py`.
2. **Train** Ultralytics YOLOv8 on Kaggle GPU (never the dev laptop) —
   `ml/train_yolo.py`, notebooks.
3. **Tune** `ml/tune_thresholds.py` → `thresholds.json` (tuned **for** those weights).
4. **Export** `ml/export_onnx.py` → `best.onnx`.
5. **Package** `build_pack.py` → `dist/packs/<crop>/<version>/`
   (model + thresholds + taxonomy + strings + KB pages).
6. **Serve** — the same artifact to the browser (WASM) and the server (CPU).

| Model | Role | Classes |
|---|---|---|
| **YOLOv8s potato pathology** (`ml/`) | the farmer app | early blight, late blight, healthy |
| **YOLOv8 CropRow** (`croprow/`) | lab: cultivator guidance, plant localiser | lettuce |
| **YOLOv8 CropHealth** (`croprow_disease/`) | lab: vigour triage | healthy, unhealthy |

Feedback loop: officer confirms/corrects a case → `TrainingSample` →
`ml/export_feedback.py` → retraining.

**The lab scanners diagnose nothing.** A box drawn around a lettuce is a
localisation, and the install page says so explicitly: *Potato* is the farmer
app, the two scans are lab tools.

---
## 17. Not built yet

| Gap | Consequence today |
|---|---|
| Local DB (Drift schema, UUID ids, outbox) | Nothing a farmer records persists or queues for upload |
| Sync worker + digest endpoint | No device contributes to cross-farm pressure; collective layer is demo or empty |
| Real weather prefetch | Synthetic feed is the *primary* source, not a cache |
| Pack signing | `signature: null`; SHA-256 is the real control |
| Release signing key | Debug key in `build.gradle.kts` |
| `packs.cropguard.in` bucket | Does not exist; builds need `--dart-define=PACK_CATALOG_BASE` |
| iOS | Not attempted (would port as WKWebView + loopback server) |

---

## 18. Diagram cheat-sheet

Node IDs match the `[N#]` labels in the §1 diagram. Use these tables when redrawing it in a diagram tool. Dashed = not built yet.

### Nodes

| ID | Node | Group |
|---|---|---|
| N1 | Flutter shell (`main.dart`) | Handset |
| N2 | Crop picker | Handset |
| N3 | WebView — React UI | Handset |
| N4 | onnxruntime-web (WASM) | Handset (inside N3) |
| N5 | LocalServer `127.0.0.1:<port>` | Handset |
| N6 | Dart domain (weather, risk, triage, taxonomy, geo) | Handset |
| N7 | KB: BM25 + advisory composer | Handset |
| N8 | Pack store | Handset |
| N9 | Installed packs `<documents>/packs/` | Handset storage |
| N10 | Demo dataset (APK asset) | Handset storage |
| N11 | APK assets `assets/web/` | Handset storage |
| N12 | Static bucket `dist/packs/**` | Cloud |
| N13 | React UI (browser) | Web |
| N14 | FastAPI backend | Server |
| N15 | SQLite / Postgres | Server |
| N16 | OpenWeatherMap | External |
| N17 | Gemini | External |
| N18 | ML training (Kaggle) → `build_pack.py` | Offline tooling |
| N19 | Golden fixtures `mobileapp/fixtures/` | Offline tooling |
| N20 | Sync worker / outbox | *not built* |

### Edges

| From → To | Label | When |
|---|---|---|
| N1 → N5 | `start()` binds port | boot |
| N1 → N8 | `activePack()` | boot, before WebView loads |
| N1 → N2 | no crop pack installed | first launch |
| N2 → N12 | `index.json`, then pack files over HTTPS | first launch only |
| N8 → N9 | verify SHA-256 → atomic move | install |
| N1 → N3 | `loadRequest(origin)` | boot |
| N3 → N5 | `fetch('/api/...')` over loopback HTTP | always |
| N5 → N11 | serve `/`, `/assets/*` | always |
| N5 → N6 | risk, weather, triage | always |
| N5 → N7 | advisory, search | always |
| N7 → N9 | read KB pages | index rebuild per `crop@version` |
| N5 → N9 | stream `model.onnx`, thresholds | scan |
| N5 → N10 | officer views (`include_demo=true`) | on request |
| N3 → N4 | run detection in-page | photo + live scan |
| N4 → N5 | detections → triage + advisory | after each scan |
| N13 → N14 | REST `/api` | web deployment |
| N14 → N15 | SQLAlchemy | web deployment |
| N14 → N16 | forecast | web deployment |
| N14 → N17 | chat | web deployment |
| N18 → N12 | publish packs | release |
| N14 ⇢ N19 ⇠ N6/N7 | `export_fixtures.py --check` (same numbers) | CI |
| N5 ⇢ N20 ⇢ N14 | case upload / cross-farm digest | *future* |

**The one fact the diagram must make visible:** there is **no edge from the
handset (N1–N11) to the FastAPI backend (N14)**. The only network edge from the
phone is N2 → N12, to a static bucket, once.
