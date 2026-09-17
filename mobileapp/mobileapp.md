# CropGuard Mobile — implementation reference

Android app for the farmer. The whole farmer loop — **weather risk forecast →
photo → diagnosis → triage → treatment advice → follow-up** — runs on the
handset with the radio off. A connection is needed exactly twice: once on first
launch to download a crop model, and afterwards only for cross-farm data that
by definition lives on other people's devices.

Officers stay on the React web app: desk work, large screens for maps and
charts, and a review queue that is inherently multi-user.

Verified state of this document's claims (re-run these to check):

| Check | Command | Result |
|---|---|---|
| Flutter/Dart tests | `flutter test` (in `app/`) | **163 passed** |
| Golden vectors vs Python | `python mobileapp/tools/export_fixtures.py --check` | **108 cases, 0 diffs** |
| Demo dataset vs generator | `python mobileapp/tools/export_demo_dataset.py --check` | **matches** |

Toolchain: Flutter 3.47.4 (stable) · Dart 3.13.3 · Java 17 · Gradle 9.3.1 ·
Kotlin JVM target 17.

---

## 1. Architecture

There is no backend server and no ONNX runtime in the Dart process. Three
layers inside one Android process:

```
┌──────────────────────────────────────────────────────────────┐
│ Flutter shell — app/lib/main.dart                            │
│   • WebView host, camera permission, file-chooser bridge     │
│   • first-launch crop picker (the one online screen)         │
├──────────────────────────────────────────────────────────────┤
│ WebView — the CropGuard React UI, bundled into the APK       │
│   • loads from http://127.0.0.1:<os-assigned-port>           │
│   • runs onnxruntime-web: photo AND live inference in-page   │
├──────────────────────────────────────────────────────────────┤
│ LocalServer — app/lib/local_server.dart (1200 lines)         │
│   • dart:io HttpServer on loopback, OS-assigned port         │
│   • serves assets/web/* out of the APK bundle                │
│   • implements the /api surface the UI already calls         │
├──────────────────────────────────────────────────────────────┤
│ Dart domain — app/lib/domain, app/lib/kb, app/lib/packs      │
│   • agronomic models, triage gate, taxonomy, weather feed    │
│   • BM25 retriever + advisory composer                       │
│   • pack download / verify / atomic install                  │
└──────────────────────────────────────────────────────────────┘
                              ▲
                    HTTPS, first launch only
                              │
              Static object storage: dist/packs/**
```

**Why a WebView rather than native Flutter screens.** The React UI already
existed, already spoke this API, and already carried the four-language strings.
Porting it to Dart widgets would have forked the farmer experience into two
implementations that drift. Instead the *backend* was ported, and the UI was
moved unchanged — `frontend/src/lib/detectPhoto.js` is the only seam, and it
branches on a capability flag rather than on a build target.

**Why loopback HTTP rather than a JS bridge.** The page issues ordinary
`fetch('/api/...')` calls. Keeping a real HTTP origin meant zero changes to
every call site, and the same payload shapes keep the web deployment and the
handset honest about each other.

### Request lifecycle

1. `main()` → `LocalServer.instance.start()` binds `127.0.0.1:0`; the OS picks
   a free port, so a fixed port cannot collide with anything else on the phone.
2. `PackStore.instance.activePack()` decides whether to show the crop picker.
   This happens **before** the WebView loads, because the scanner reads
   `/detect/status` once at startup — a pack installed afterwards would leave
   the page convinced there is no detector until a manual reload.
3. The WebView loads the origin. `/` and `/assets/*` are read straight out of
   the APK via `rootBundle` with `Cache-Control: immutable`.
4. `/api/*` is dispatched by a single `switch` in `LocalServer._api`.
   Unmatched paths return **503** with an explicit reason, never a fake 200.

---

## 2. What is offline and what is online

This is the section to read first. The rule throughout is **state the absence,
never fabricate the data.**

### Fully offline — works in airplane mode

| Capability | Implementation | Held to |
|---|---|---|
| Weather feed | `domain/weather.dart` — deterministic synthetic series, seeded by SHA-256 of rounded coords + date/hour | matches the server's `_seeded_unit` exactly |
| Risk models | `domain/risk_models.dart` — Smith Period, Beaumont Period, TOMCAST DSV, growing degree-days | `fixtures/risk_models.json`, 40 cases |
| Geo / hotspot cells | `domain/geo.dart` | `fixtures/geo.json`, 18 cases |
| Triage safety gate | `domain/triage.dart` | `fixtures/triage.json`, 25 cases |
| Class taxonomy, 4 languages | `domain/taxonomy.dart` | `offline_engine_test.dart` |
| Photo diagnosis | onnxruntime-web **inside the WebView**, weights served from the installed pack | `pack_store_test.dart` + frontend tests |
| Live camera scanner | same session, same weights | — |
| Lab scanners (crop row, crop health) | their own detector packs | — |
| Advisory / RAG | `kb/knowledge_base.dart` (BM25) + `kb/advisory.dart` | `fixtures/kb.json`, 25 cases |
| Dose tables | **parsed** from reviewed markdown in the pack, never generated | the markdown file itself |
| Follow-up scheduling | `kb/advisory.dart`, `kFollowUpDays` | — |
| Officer screens on demo data | `demo/demo_api.dart` over the bundled dataset | `export_demo_dataset.py --check` |

### Needs a connection

| Capability | Why | What the app does without it |
|---|---|---|
| **Downloading a crop pack** | 45 MB of weights are not in the APK | Crop picker says so plainly, and is **skippable** — risk forecasting works with no pack |
| Pack catalogue (`/packs/catalog`) | reads `index.json` from the bucket | 503 with the real message; "Could not get the crop list" |
| Cross-farm outbreak pressure, hotspot map | needs other farmers' cases | Demo data, or genuinely empty — the farmer's toggle chooses |
| Officer dashboard, review queue | same | same |
| Chat assistant (`/chat/status`) | `mode: "offline"` | Says the assistant needs a connection and names what still works |
| Real weather forecast prefetch | **not built yet** | Synthetic feed is the primary source |
| Sync / outbox upload | **not built yet** | Cases stay on the device |

### The `include_demo` toggle

The officer screens have two honest answers offline, and which one you get is
the farmer's choice, not the app's:

* `include_demo=true` (the UI's "Demo + live" toggle, and the default) serves
  the synthetic dataset bundled in the APK.
* `include_demo=false` serves genuinely empty results, because this device
  holds no other farmers' cases until it syncs.

Either way **the payload shape is the server's**. The UI reads these payloads
positionally (`summary.cases.total`, `rows.find(...)`), so an
`{items: [], offline: true}` envelope is not a softer failure than a 500 — it
is a harder one: the read throws during render, React unmounts the tree, and
the farmer gets a white screen with no way back. Empty payloads therefore carry
every key the full ones do, including `unverified_weight` (0.4) and
`severe_threshold` (8.0), which are mirrored from
`backend/app/routers/hotspots.py` so the heat ramp does not silently re-scale
the day sync fills it in.

### `/api/meta/health` reports it rather than hiding it

```json
{ "status": "ok", "mode": "offline", "degraded": [],
  "by_design": [
    {"code": "offline_build",         "detail": "Running fully on-device …"},
    {"code": "detector_not_bundled",  "detail": "No image detection model ships in this build …"}
  ] }
```

`degraded` stays empty because none of this is a fault. Everything absent is in
`by_design`, with a reason string the UI can show.

---

## 3. Where inference actually runs

There is no ONNX runtime in the app's Dart process, and there is no server to
upload a photograph to. There *is* one already in the WebView, fetching these
same weights for the live scanner — so the page runs the model itself.

```
Farmer taps "Check crop", picks a photo
        │
        ▼
frontend/src/lib/detectPhoto.js
        │
        ├─ GET /api/detect/status
        │     server build  → no `inference` key  → POST /api/detect (upload, unchanged)
        │     handset       → inference: "in_page"
        │
        ├─ decode image → createImageBitmap (falls back to <img> on old WebViews)
        ├─ LiveDetector session (built once, cached — weights are tens of MB)
        ├─ GET /api/detect/model  → weights read straight off disk from the pack
        └─ detections → POST back to the LOCAL api for:
               • the triage gate      (offline)
               • the advisory + doses (offline)
               • the risk forecast    (offline)
```

Only the pixels needed the page. Everything judgemental stays in the ported
domain code, so the phone and the server reach the same verdict from the same
detections.

**`/api/detect` on the handset never says "needs a network connection."** With
no pack it names the crop to install; with a pack it says to reload. Both
return 503 with `model_available` set correctly. A farmer standing in a field
being told to find signal for a diagnosis their phone could already do — with
the model downloaded and sitting on disk — was the specific failure this
design exists to avoid.

**Honest absence beats a guess.** When no model is installed, `detectPhoto`
still returns a full response: no class, no confidence, but a triage verdict, an
escalation route and a note explaining why there is no diagnosis. Cases route to
the expert queue rather than returning a confident wrong label.

### The two ORT copies in the bundle

`assets/web/assets/ort-wasm-simd-threaded-*.wasm` (13.96 MB, Vite-hashed) and
`assets/web/ort/ort-wasm-simd-threaded.wasm` (13.96 MB, stable name) are both
shipped. `onnxruntime-web` resolves the runtime by a path it computes at
session creation, and the hashed name alone did not satisfy every resolution
path; the stable copy is what makes session creation work from the local
origin. That is 14 MB of the APK and the single largest thing that could be
trimmed later.

One trap, recorded in `tools/stage_web.ps1` because it cost a day: deleting the
`*jsep*` (WebGPU) runtime looks safe — the live detector asks for the wasm
provider with `numThreads=1` — but the default `onnxruntime-web` entry
*dynamically imports* `ort-wasm-simd-threaded.jsep.mjs` at session creation
regardless of the provider requested. Deleting it made every on-device session
fail with "no available backend found", and because the local server answers a
missing file with `index.html`, the browser reported a **MIME type error rather
than a 404**. `liveDetector` now imports `onnxruntime-web/wasm`, which never
asks for jsep, so the build no longer emits it; the deletion loop stays as
belt-and-braces against a dependency bump reintroducing it.

---

## 4. Crop packs

**A crop is a downloadable pack, not an app release.** Weights alone are not a
pack: a model that predicts `tomato_late_blight` with no dose table, no Marathi
string and no taxonomy entry produces a diagnosis the app cannot safely advise
on — which, given the safety gating, is worse than not supporting the crop.

### On-disk / on-bucket layout

```
dist/packs/index.json                       the catalogue, a few hundred bytes
dist/packs/potato/1.0.1/manifest.json       per-file SHA-256, min_app_version
dist/packs/potato/1.0.1/model.onnx          the weights
dist/packs/potato/1.0.1/thresholds.json     tuned FOR those weights
dist/packs/potato/1.0.1/taxonomy.json       class list, in model index order
dist/packs/potato/1.0.1/strings.json        class names + advisory text, 4 langs
dist/packs/potato/1.0.1/kb/*.md             the pages the advisory is built from
```

The phone fetches `index.json` **first** — a few hundred bytes before deciding
whether to pull 45 MB, which matters on a metered rural connection.

### What is published today

| Pack | Kind | Version | Size | Classes |
|---|---|---|---|---|
| `potato` | crop | 1.0.1 | 44,818,247 B (~45 MB) | `potato_early_blight`, `potato_late_blight`, `potato_healthy` |
| `croprow` | detector | 1.0.0 | 10,604,888 B (~11 MB) | `lettuce` |
| `crophealth` | detector | 1.0.0 | 10,605,864 B (~11 MB) | `healthy`, `unhealthy` |

The potato pack's six KB pages: `potato_early_blight.md`, `potato_late_blight.md`,
`potato_healthy.md`, `potato_pests.md`, `referral_and_ipdm.md`,
`safe_input_usage.md`.

### Two kinds of pack, and why the distinction is load-bearing

| | `crop` | `detector` |
|---|---|---|
| Example | `potato` | `croprow`, `crophealth` |
| Contents | model, thresholds, taxonomy, strings, KB pages | model, thresholds, taxonomy |
| Drives | photo diagnosis, triage, treatment advice | one lab scanner |

A crop pack without its KB pages is a bug — it could diagnose and never advise.
A detector pack without them is *correct*, because a box drawn around a lettuce
is not advice and must not be dressed up as any.

`activePack()` — what `/detect` serves the farmer from — considers **crop packs
only**. Without that rule, installing "Crop row scan" would repoint the potato
scanner at a single-class lettuce localiser and return boxes labelled "lettuce"
with no error anywhere. `pack_store_test.dart` pins it both ways: a detector
never becomes active, and a detector installed alone leaves the crop scanner
reporting *nothing* rather than reporting a lettuce.

The lab endpoints also answer in a **deliberately different shape** from the
potato ones: `/croprow/status` returns `available`, `/detect/status` returns
`model_available`. Not tidy — but the pages were written against the server's
shapes, and quietly renaming a key here reads as "no model installed" with
nothing in any log.

### What the installer refuses

Download → verify → **then** swap. Everything is staged in a temporary
directory and moved into place only once the whole set passes. A pack that
fails any check leaves nothing behind. This is not ceremony: the payload is a
table of pesticide doses, and TLS protects the transport, not a compromised
bucket or a wrong upload.

`app/test/pack_store_test.dart` asserts each refusal against a real HTTP server:

| Refusal | Test |
|---|---|
| A file whose bytes fail its SHA-256 | "refuses a pack whose file fails its checksum, and installs nothing" |
| A truncated body | same suite |
| Manifest describing a different crop/version than the catalogue offered | `Refusing to install.` |
| `min_app_version` above this build (`kAppVersion = 1.0.0`) | "Update the app first." |
| Version ordering (`1.0.10` > `1.0.9`) | "compareVersions orders numerically, not lexically" |
| Rollback to an older version | "installing an older version rolls back rather than keeping the newer" |
| An unparseable manifest already on disk | left for forensics, never half-served |

**Packs install into the app documents directory, never the cache directory.**
Android evicts cache under storage pressure, and a pack that vanished mid-season
would break offline use precisely when the farmer cannot re-download it.

> **Signing is scaffolded, not enforced.** `manifest.signature` exists in the
> format and `PackStore.install` checks it — but `allowUnsigned` defaults to
> `true` and `build_pack.py` writes `"signature": null`, so today nothing is
> signed. SHA-256 per file is the real integrity control. Closing this means
> generating a key, signing the file list in `build_pack.py`, and flipping
> `allowUnsigned` to `false`.

### Building packs

```bash
python mobileapp/tools/build_pack.py --crop potato --version 1.0.1
python mobileapp/tools/build_pack.py --version 1.0.0 --detector croprow --detector crophealth
python mobileapp/tools/build_pack.py --index          # rebuild the catalogue
```

Output lands in `dist/packs/`, which is gitignored in the main repo
(`/dist/packs/` in `.gitignore`) and synced to object storage instead. The
layout is flat and static — no server, no database, no API — so it can live on
S3, R2, Cloudflare, GitHub Pages or any bucket that serves files over HTTPS.

**`build_pack.py` writes UTF-8 with LF line endings, always.** `Path.write_text`
opens in text mode, so on Windows every newline becomes CRLF — and the manifest
hashes *those* bytes. A pack built on Windows and served from anywhere that
normalises line endings (git, and therefore GitHub Pages) fails its own
checksum on install. This actually happened: three of the ten potato files no
longer matched the hashes published alongside them, and the installer refused
the pack — correctly, and unhelpfully, since the pack was ours.

Hence the pre-push guard, run from the publishing worktree with the site staged:

```bash
python mobileapp/tools/verify_published_packs.py
```

It hashes the **staged git blob** for each manifest entry — the exact bytes that
get pushed, and therefore exactly what the host serves — and compares it to the
published SHA-256. Anything git transformed on the way in shows up here rather
than on a farmer's phone.

### Pointing the app at a bucket

**At runtime, no rebuild** — Menu → Crop models → *Where crops are downloaded
from*. Stored in `<documents>/packs/catalog_url` and survives app updates. This
exists because a build-time-only constant means a handset pointed at a host that
later goes away can never be recovered without reinstalling, which is not
something you can ask a farmer to do. The same value is readable and settable
over the API at `GET|POST /api/packs/source`, which also reports
`compiled_default`.

**At build time:**

```bash
flutter build apk --release \
  --dart-define=PACK_CATALOG_BASE=https://your-bucket.example.com/packs
```

> The compiled default in `app/lib/packs/pack_store.dart` is
> `https://packs.cropguard.in/packs`, which **does not exist yet**. Until that
> bucket is real, every build needs the `--dart-define` above or the crop picker
> shows "Could not get the crop list".

**Testing with no bucket at all** — serve `dist/` from your machine over the
same wifi:

```bash
python -m http.server 8099 --bind 0.0.0.0     # from dist/
ipconfig                                       # note the LAN address
```

Then set `http://<your-lan-ip>:8099/packs` in Menu → Crop models. Over USB,
`adb reverse tcp:8099 tcp:8099` and `http://127.0.0.1:8099/packs` works too.

Plain HTTP is fine for either. `network_security_config.xml` governs the
**WebView** (which is why loopback is listed there), but pack downloads go
through Dart's `dart:io` sockets, which Android's cleartext policy does not
apply to. Use HTTPS in production regardless — the manifest will not stop you
either way, and the payload is a table of pesticide doses.

### Install is asynchronous on purpose

A 45 MB download takes a minute or more on a rural connection.
`POST /api/packs/install` validates the body, returns **202** immediately and
runs the transfer in the background; the UI polls `GET /api/packs/progress`
for `{active, phase, received_bytes, total_bytes, file}` where phase is
`catalog | manifest | download | verify | install | done`. Holding the HTTP
request open for the whole transfer would give the page a choice between a dead
spinner and a timeout, and neither tells the farmer whether to keep waiting.
A second concurrent install gets **409** with the in-flight progress attached.
Body validation happens *before* the 409 check, because a malformed body is
malformed whether or not something else is running.

---

## 5. The on-device API surface

Every route below is served by `app/lib/local_server.dart` on
`http://127.0.0.1:<port>/api`. **O** = fully offline, **N** = needs a network,
**D** = demo-data-backed offline (empty when `include_demo=false`).

### Meta

| Route | | Notes |
|---|---|---|
| `GET /meta/health` | O | `mode: offline`, `degraded: []`, `by_design: [...]` |
| `GET /meta/classes` | O | crop, class list, `non_model_threats` |
| `GET /meta/languages` | O | en, mr (मराठी), hi (हिन्दी), bn (বাংলা) |

### Risk and forecasting

| Route | | Notes |
|---|---|---|
| `GET /home/overview` | O | defaults to 18.52, 73.86 (Pune) |
| `POST /risk` · `GET /risk` | O | coords from body or query |
| `GET /risk/weather` | O | deterministic synthetic series |
| `GET /risk/models` | O | Smith (1956); Beaumont (1947); TOMCAST (Pitblado; Madden/Pennypacker); single-triangle degree-days — each with its citation |

### Detection

| Route | | Notes |
|---|---|---|
| `GET /detect/status` | O | `model_available`, **`inference: "in_page"`** |
| `GET /detect/model` | O | the weights, straight off disk |
| `GET /detect/thresholds` | O | per-class cut-offs from the pack |
| `POST /detect`, `/detect/frame` | — | **503 by design** — inference is in-page; the message says which crop to install and states "This is not a network problem" |
| `GET /croprow/status`, `/crophealth/status` | O | returns `available` (not `model_available` — the server's shape) |
| `GET /croprow/model`, `/crophealth/model` | O | detector weights |
| `GET /croprow/thresholds`, `/crophealth/thresholds` | O | |

### Advisory

| Route | | Notes |
|---|---|---|
| `GET /advisory/status` | O | `backend: "lexical-bm25"`, document/chunk counts, active pack, `offline: true` |
| `GET /advisory/search` | O | BM25 over the pack's KB pages |
| `POST /advisory` | O | composed advisory: actions, doses, safety bullets, follow-up date |

### Packs

| Route | | Notes |
|---|---|---|
| `GET /packs/installed` | O | each with `kind`, `classes`, `active` |
| `GET /packs/catalog` | **N** | 503 with the real reason offline — the one call that genuinely needs a connection |
| `GET|POST /packs/source` | O | runtime catalogue URL + `compiled_default` |
| `POST /packs/install` | **N** | 202 and runs in background; 400 on bad body; 409 if one is running |
| `GET /packs/progress` | O | poll target |

### Officer / collective views

| Route | | Empty-payload keys preserved |
|---|---|---|
| `GET /hotspots` | D | `window_days`, `cell_size_deg`, `unverified_weight`, `total_*`, `cells` |
| `GET /hotspots/points` | D | + `severe_threshold: 8.0` |
| `GET /review/queue` | D | JSON **array** (`list[CaseOut]` on the server) |
| `GET /followups`, `/sensors` | D | JSON arrays |
| `GET /dashboard/summary`, `/trend`, `/districts` | D | |
| `GET /review/stats/accuracy` | D | |
| `GET /followups/stats`, `/sensors/summary` | D | |
| `GET /dashboard/cases` | — | always `[]` |
| `GET /chat/status` | — | `mode: "offline"` + what still works |

**Anything unmatched** returns 503 `"This feature needs a network connection and
is not available in the offline build."`

---

## 6. The Dart domain port, and how it is kept honest

The agronomic models, the triage gate, the geo maths and the retriever were
ported from Python to Dart. A port is only as good as its evidence, so the
Python services were first pinned to **golden vectors** — language-neutral JSON
of inputs and expected outputs — and the Dart is held to the same numbers.

```bash
python mobileapp/tools/export_fixtures.py --check    # verify (CI)
python mobileapp/tools/export_fixtures.py --write    # regenerate
```

| Suite | Cases | Dart test |
|---|---|---|
| `fixtures/geo.json` | 18 | `test/fixtures_geo_test.dart` |
| `fixtures/kb.json` | 25 | `test/fixtures_kb_test.dart` |
| `fixtures/risk_models.json` | 40 | `test/fixtures_risk_models_test.dart` |
| `fixtures/triage.json` | 25 | `test/fixtures_triage_test.dart` |
| **Total** | **108** | |

Read [`fixtures/FORMAT.md`](fixtures/FORMAT.md) before adding a case —
particularly the rule that **a failing `--check` is read, not regenerated away.**

Two real differences the fixtures caught:

* **Sort stability.** Python's `list.sort` is stable; Dart's is not. Tied BM25
  chunks came back in a different order until the Dart side broke ties on
  corpus index.
* **Numeric formatting.** `domain/num_compat.dart` exists because Dart and
  Python disagree about how numbers print and round at the edges, and a dose
  that renders as `2.5` on one and `2.50000000000000004` on the other is a
  support ticket.

The weather feed's determinism is the same kind of contract: the seed is
SHA-256 of the rounded coordinates plus date/hour, matching `_seeded_unit`
exactly. A different hash here would mean the phone and the server disagree
about the forecast for the same field.

---

## 7. Offline advisory (RAG)

Retrieval runs on the handset, over the KB pages in the installed pack. **There
is no vector backend and no embedding model — BM25 is the implementation, not a
fallback.** That is an honest fit rather than a compromise: the corpus is six
markdown pages, the query is a class key plus a few field terms, and the
retrieval unit is a markdown section.

`app/lib/kb/knowledge_base.dart` is a port of the Python retriever, and
`fixtures/kb.json` pins the tokenizer, the chunking **and the BM25 scores**, so
the same question gives a farmer and an officer the same dose table.

`app/lib/kb/advisory.dart` is the deterministic half of
`backend/app/services/advisory.py`. The server runs it as a LangGraph pipeline
(retrieve → compose → safety → localize); the same four steps are four function
calls here, because a graph runtime buys orchestration a handset does not need.

**Nothing generative is ported, because nothing generative exists.** Doses are
*parsed* out of reviewed markdown tables on the server too. The numbers a
farmer sprays by stay accountable to a file an agronomist can correct in a pull
request — which matters more on a handset, not less, because there is nobody
there to catch a hallucinated dose.

The index is rebuilt only when the active pack changes (keyed on
`crop@version`), not per query.

---

## 8. Demonstration data on the handset

```bash
python mobileapp/tools/export_demo_dataset.py --write
python mobileapp/tools/export_demo_dataset.py --check   # CI guard
```

Writes `app/assets/demo/dataset.json` — 300,440 bytes, seed 2026, 90-day
window: **120 cases, 120 follow-ups, 520 trap readings** across the Maharashtra
potato districts. The app derives the dashboard, the hotspot cells, the review
queue and the follow-up statistics from those rows, so the period selector and
the district filter genuinely filter rather than moving four fixed numbers.

The officer screens are meaningless against an empty database, and a handset has
no other farmers' cases until it syncs. Without this the phone shows a
technically-correct wall of zeros, which in a demo reads as "broken" and in the
field reads as "no disease anywhere".

Two properties worth knowing:

* **Records store day offsets, not timestamps**, materialised against the clock
  when the asset loads. A fixed timestamp would mean an APK built in September
  shows September cases at Christmas, with an empty "last 7 days" window.
* **It is never passed off as real.** Every record carries `demo: true`, farmer
  names start "Demo", and the model version is `demo-seed`. The UI's existing
  "Demo + live / Live only" toggle drives it.

It is a sibling of `scripts/seed_demo_data.py`, not a replacement: that one
seeds the server's SQLite for the web app, this one produces a read-only asset
for the handset. Neither reads the other's output.

It is parsed once and held in memory — re-parsing 293 KB of JSON per request
would be visible on a cheap handset.

---

## 9. Android specifics — the non-obvious ones

Each of these was an invisible failure before it was a line of config.

### `INTERNET` must be in the *main* manifest

Flutter only declares `android.permission.INTERNET` for debug and profile
builds. A release build without it in `src/main/AndroidManifest.xml` **loads
nothing and fails silently** — including the loopback server.

### Cleartext, but only for loopback

Android blocks cleartext HTTP from API 28 onward and the WebView enforces it:
`http://127.0.0.1:<port>` fails with `ERR_CLEARTEXT_NOT_PERMITTED` and no
useful message. `res/xml/network_security_config.xml` permits `127.0.0.1` and
`localhost` only, with `<base-config cleartextTrafficPermitted="false"/>`.

A blanket `android:usesCleartextTraffic="true"` would also permit unencrypted
traffic to any server on the internet — a real downgrade for an app that will
later sync farmer names, phone numbers and plot coordinates.

### File inputs need the host's help

Android's WebView does not open a file chooser on its own. It asks the host via
`onShowFileChooser`, and a host that does not answer leaves the tap **silently
dead** — no picker, no error, no console message, nothing in logcat.
`main.dart` answers it with `setOnShowFileSelector(_pickFiles)`.

This is worth knowing because the failure is invisible from the web side. Every
`<input type="file">` in the bundled UI depends on it: video upload on both lab
scanners, and the photo picker on Check crop. All three looked like UI bugs and
none of them were.

The handler narrows the picker to what the input asked for — `accept="video/*"`
opens videos, not a photo grid — because a farmer picking a still that the clip
scanner then refuses is a worse experience than no picker at all. It also
returns an empty list on *any* exception: a picker that throws without
returning leaves the input in a pending state, and the next tap does nothing
either.

### Camera

`Permission.camera` is requested at boot rather than letting the WebView's own
prompt appear with no context mid-scan. On Android the controller also sets
`setMediaPlaybackRequiresUserGesture(false)` and grants the WebView's own
permission request, so `getUserMedia` works without a synthetic gesture.

### Console forwarding

`setOnConsoleMessage` forwards the page's console to logcat. Without it a
JavaScript error inside the bundled UI is completely invisible: the WebView goes
white, `onWebResourceError` says nothing because the document loaded fine, and
there is no way to tell a blank page from a crashed one. `adb logcat -s flutter`
now shows the actual stack.

Subframe and asset errors are filtered out of the user-facing error pane
(`err.isForMainFrame != true` returns early) — they are noisy and mostly
harmless.

### Back button

`PopScope(canPop: false)` walks the WebView's own history first and only then
pops the route, so Back does not drop the user out of the app from three
screens deep.

### Dependency and Gradle notes

* **`flutter_plugin_android_lifecycle` is pinned to 2.0.24** in
  `dependency_overrides`. `file_picker` pulls it in, and 2.0.35 demands
  consumers compile against API 36 while `file_picker` itself still compiles
  against 34 — a skew inside the plugin's own dependency tree. The alternative,
  forcing every plugin module's `compileSdk` from the root Gradle script, has to
  fight Gradle's evaluation order and did not work.
* **`kotlin.incremental=false`.** Its cache repeatedly corrupted itself here
  ("Could not close incremental caches", "Storage for [...] is already
  registered"). The trigger was the pub cache on `C:` with the project on `D:` —
  Kotlin's path converter calls `File.relativeTo()`, which throws across drive
  letters — and once poisoned, the daemon kept re-registering stale storages
  even after the drive mismatch was fixed. `PUB_CACHE` now points at
  `D:\dev\pub-cache`, but the incremental cache buys almost nothing here (two
  small plugin modules), so the flag stays.
* `org.gradle.jvmargs=-Xmx8G` with 4G metaspace — the bundled 28 MB of web
  assets makes packaging memory-hungry.

---

## 10. Building the APK

### Identity

| | |
|---|---|
| Application ID | `in.cropguard.cropguard` |
| Label | CropGuard |
| Version | `1.0.0+1` (pubspec) → `versionName 1.0.0`, `versionCode 1` |
| `kAppVersion` (pack gate) | `1.0.0` — keep in step with pubspec |
| Namespace | `in.cropguard.cropguard` |
| Java / Kotlin target | 17 |
| compileSdk / minSdk / targetSdk | Flutter defaults (`flutter.*`) |

### Full build, from a clean checkout

```bash
# 1. Build the web UI and stage it into the app's assets.
#    Run this after ANY frontend change.
pwsh mobileapp/tools/stage_web.ps1

# 2. Regenerate the demo asset if the generator changed.
python mobileapp/tools/export_demo_dataset.py --write

# 3. Build.
cd mobileapp/app
flutter pub get
flutter test                       # 163 tests
flutter build apk --release \
  --dart-define=PACK_CATALOG_BASE=https://<your-bucket>/packs
```

The APK lands at `mobileapp/app/build/app/outputs/flutter-apk/app-release.apk`.

> **`assets/web/` is gitignored build output, not source.** Forgetting to re-run
> `stage_web.ps1` means the APK ships a stale UI, and the mismatch is invisible
> until someone notices a fix missing on the phone. Flutter does not recurse
> into asset subdirectories, so `pubspec.yaml` lists `assets/web/`,
> `assets/web/assets/`, `assets/web/ort/` and `assets/demo/` individually —
> a new subdirectory in the frontend build output needs a new line there.

### What is in the 54 MB

| Component | Size |
|---|---|
| Published APK | 56,098,065 B (53.5 MiB, "54 MB" on the install page) |
| ├─ ORT wasm runtime ×2 | 27.9 MB |
| ├─ UI bundle (`index-*.js` + `.css`) | ~1.0 MB |
| ├─ demo dataset | 293 KB |
| └─ Flutter engine, Dart AOT, resources | remainder |

**No model weights are in the APK.** Every crop is downloaded, including potato.
Bundling it would add ~45 MB to every install and — worse — would leave the
download-verify-swap path as a rarely-exercised branch that first runs in anger
the day a second crop ships. One code path, used from the first launch, is the
safer trade. The cost is that first launch needs a connection once, which the
crop picker states plainly and allows you to skip.

> **Release builds are signed with the debug key.** `android/app/build.gradle.kts`
> still carries `signingConfig = signingConfigs.getByName("debug")` with the
> template's TODO. Fine for `flutter run --release` and for handing an APK
> round; **not** fine for any real distribution channel, and it means a
> later properly-signed build cannot upgrade an installed debug-signed one —
> users have to uninstall first.

---

## 11. Distribution

`dist/` holds the install page, built as a plain static site:

```
dist/index.html            the landing/install page (dark-mode aware)
dist/cropguard.apk         the build
dist/cropguard.apk.sha256  e1c3663d…c84cd32
dist/packs/**              the catalogue and the packs
```

The page tells the farmer the three things that actually matter: it is Android
only and the browser will need install permission; it needs a connection
**exactly once** for the crop download; and *Potato* is the farmer app while
the two scans are lab tools that locate plants and diagnose nothing.

`dist/` is gitignored in the main repo and published from a separate worktree —
run `verify_published_packs.py` from there before pushing.

---

## 12. Tests

```bash
cd mobileapp/app && flutter test        # 163 passing
```

| File | Covers |
|---|---|
| `fixtures_geo_test.dart` | 18 golden geo cases |
| `fixtures_kb_test.dart` | 25 golden BM25 cases — tokenizer, chunking, scores |
| `fixtures_risk_models_test.dart` | 40 golden agronomic-model cases |
| `fixtures_triage_test.dart` | 25 golden triage cases |
| `offline_engine_test.dart` | end-to-end offline behaviour: "no bundled detector routes to a human, never to a guess"; "healthy crop under high risk is a preventive window, not an alarm"; "every class names itself in all four languages"; "healthy is never actionable" |
| `pack_store_test.dart` | catalogue read, good install, checksum refusal, rollback, detector-never-active, numeric version ordering — all against a real HTTP server |
| `api_contract_test.dart` | the JSON **type and keys** of every offline payload — not the values, which are legitimately zero on a device holding no cases. This is the guard against the white-screen failure described in §2 |
| `widget_test.dart` | the cold-start hint stays hidden until the wait is actually long |

Python-side guards: `export_fixtures.py --check`,
`export_demo_dataset.py --check`, `verify_published_packs.py`.
Frontend-side: `frontend/src/lib/__tests__/detectPhoto.test.js` covers both
branches of the `inference: in_page` seam.

`export_fixtures.py` needs the backend's dependencies — run it from the repo
venv (`.venv/Scripts/python.exe`), not a bare `python`, or it fails on
`pydantic_settings`.

---

## 13. Not built yet

Stated here rather than left to be discovered:

| Gap | Consequence today |
|---|---|
| **Drift schema, UUID ids, outbox** | Cases live only in the demo asset and in memory; nothing a farmer records persists to a local DB or queues for upload |
| **Sync worker + digest endpoint** | No device ever contributes to cross-farm outbreak pressure; the collective layer is demo data or empty |
| **Weather prefetch** | The deterministic synthetic feed is the *primary* source, not a cache of a real forecast |
| **Pack signing** | `signature: null` everywhere; `allowUnsigned` defaults true. SHA-256 is the real control |
| **Release signing key** | Debug key in `build.gradle.kts` |
| **`packs.cropguard.in`** | Does not exist; every build needs `--dart-define=PACK_CATALOG_BASE` |
| **iOS** | Not attempted. The architecture ports (WKWebView + a loopback server), but nothing has been tried |

### Two safety questions on the record

Both surfaced while pinning the triage branches. They are judgement calls, so
they are recorded rather than quietly changed — the fixtures make the current
answer visible and keep Dart and Python agreeing on whatever is decided.

1. **`conflicting_signals` escalates but still permits self-treatment**, at
   `routine` urgency. The reason text says *"the wrong product here wastes
   money and leaves residue for no benefit"* — yet `self_treatment_allowed`
   stays `true`, so nothing stops the farmer acting on the disputed diagnosis.
   Compare `low_confidence`, which sets it `false` for a weaker reason to doubt
   the label.

2. **`high_severity` escalates to district at `urgent` but also leaves
   `self_treatment_allowed` true.** This one is arguably right — telling a
   farmer with 70% of the field affected to do nothing until an officer arrives
   is its own harm — but it should be a decision on the record, not a
   consequence of rule 7 not setting the flag.

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Could not get the crop list" | Catalogue URL unreachable — usually the non-existent default bucket | Menu → Crop models → set the URL, or rebuild with `--dart-define=PACK_CATALOG_BASE` |
| White screen after splash | JS error in the bundled UI | `adb logcat -s flutter` — console is forwarded; look for `[cropguard][web]` |
| "CropGuard could not start" | The loopback server failed to bind | `adb logcat` for `[cropguard] server failed to start`. Not a network problem — the pane says so |
| Photo picker / video upload does nothing | `setOnShowFileSelector` not wired, or the picker threw | Check `[cropguard] file selector failed` in logcat |
| `ERR_CLEARTEXT_NOT_PERMITTED` | `network_security_config.xml` missing or not referenced from the manifest | Both must be present; loopback only |
| Release build loads nothing, silently | `INTERNET` missing from `src/main/AndroidManifest.xml` | Flutter only adds it for debug/profile |
| "no available backend found" at session creation | A `*jsep*` ORT file was deleted, or `assets/web/ort/` is missing from `pubspec.yaml` | Re-run `stage_web.ps1`; check the asset list |
| MIME type error instead of 404 for a web asset | The local server answers missing files with `index.html` | The file genuinely is not in the bundle — check staging |
| Pack install refused with a checksum error on **our own** pack | CRLF/LF transformation by git between build and publish | `verify_published_packs.py` from the publishing worktree; rebuild with `build_pack.py` |
| A fix is missing on the phone but present on the web | `assets/web/` is stale | `pwsh mobileapp/tools/stage_web.ps1`, then rebuild the APK |
| Kotlin build fails with "Storage for [...] is already registered" | Incremental cache corruption | Already disabled via `kotlin.incremental=false`; if it returns, `flutter clean` and check `PUB_CACHE` is on the same drive as the project |
| Dashboard shows all zeros | `include_demo=false` (the "Live only" toggle) | Correct behaviour — this device holds no other farmers' cases until it syncs |

---

## 15. File map

| Path | What |
|---|---|
| `app/lib/main.dart` | Flutter shell: WebView host, permissions, file-chooser bridge, boot sequence |
| `app/lib/local_server.dart` | The offline backend — static assets + the whole `/api` surface |
| `app/lib/domain/weather.dart` | Deterministic synthetic weather feed |
| `app/lib/domain/risk_models.dart` | Smith, Beaumont, TOMCAST, degree-days |
| `app/lib/domain/triage.dart` | The safety gate |
| `app/lib/domain/taxonomy.dart` | Classes, threat keys, four-language names |
| `app/lib/domain/geo.dart` | Hotspot cell maths |
| `app/lib/domain/num_compat.dart` | Python-compatible number formatting/rounding |
| `app/lib/kb/knowledge_base.dart` | BM25 retriever |
| `app/lib/kb/advisory.dart` | Advisory composer — actions, doses, safety, follow-up |
| `app/lib/packs/pack.dart` | Pack/manifest model |
| `app/lib/packs/pack_store.dart` | Download, verify, atomic install, active-pack rules |
| `app/lib/packs/crop_picker.dart` | First-launch crop selection — the one online screen |
| `app/lib/demo/demo_dataset.dart` | Loads and materialises the demo asset |
| `app/lib/demo/demo_api.dart` | Derives dashboards, hotspots, queues from demo rows |
| `tools/build_pack.py` | The only supported way to produce a pack |
| `tools/verify_published_packs.py` | Pre-push guard against git byte transformation |
| `tools/export_fixtures.py` | Golden vectors from the Python services |
| `tools/export_demo_dataset.py` | The bundled demo asset |
| `tools/stage_web.ps1` | Builds the frontend and stages it into the APK assets |
| `fixtures/FORMAT.md` | Read before adding a golden case |
| `frontend/src/lib/detectPhoto.js` | The one seam between server-inference and in-page inference |
