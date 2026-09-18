# CropGuard Mobile — offline-first Android app

Flutter farmer app for CropGuard. The farmer's whole loop — forecast, scan,
diagnose, advise, follow up — runs **with the radio off**. Collective
intelligence (cross-farm outbreak pressure) and expert verification are
eventually consistent, with staleness shown rather than hidden.

Officers stay on the existing React web app: they work at a desk, need large
screens for maps and charts, and the review queue is inherently multi-user.

## Status

| Step | State |
|---|---|
| 1. Golden-vector fixtures | **done** — 108 cases across geo, risk models, triage, KB |
| 2. Dart domain port | **done** — `app/lib/domain/`, green against the Python vectors |
| 3. Drift schema, UUID ids, outbox | not started |
| 4. Detection | **done** — crop packs + in-WebView ONNX, no server |
| 5. Advisory (KB in pack, Dart BM25) | **done** — `app/lib/kb/` |
| 6. Farmer UI | **done** — bundled web UI on a local origin |
| 7. Sync worker + digest endpoint | not started |
| 8. Weather prefetch | not started (deterministic synthetic feed in the meantime) |

Nothing here requires Flutter yet. Step 1 is pure Python and runs against the
existing backend.

## Layout

```
mobileapp/
  fixtures/          Language-neutral golden vectors. See FORMAT.md.
  tools/             Fixture generator + CI guard (Python).
  cropguard_domain/  Pure Dart domain package.            (step 2)
  app/               Flutter application.                 (step 6)
  packs/             Crop packs, pack-shaped from day one. (step 5)
```

## Crop packs: building and hosting

```bash
python mobileapp/tools/build_pack.py --crop potato --version 1.0.0
python mobileapp/tools/build_pack.py --version 1.0.0     --detector croprow --detector crophealth
python mobileapp/tools/build_pack.py --index        # rebuild the catalogue
```

Output lands in `dist/packs/`, which is the directory you sync to object
storage. The layout is flat and static — no server, no database, no API — so it
can live on S3, R2, Cloudflare or any bucket that serves files over HTTPS:

```
dist/packs/index.json                     the catalogue, a few hundred bytes
dist/packs/potato/1.0.0/manifest.json     per-file SHA-256
dist/packs/potato/1.0.0/model.onnx        the weights
dist/packs/potato/1.0.0/thresholds.json   tuned FOR those weights
dist/packs/potato/1.0.0/taxonomy.json     class list, in model index order
dist/packs/potato/1.0.0/strings.json      class names + advisory text, 4 langs
dist/packs/potato/1.0.0/kb/*.md           the pages the advisory is built from
```

The phone fetches `index.json` first — a few hundred bytes before deciding
whether to pull 45 MB, which matters on a metered rural connection.

**Point the app at your bucket, without rebuilding:**

Menu > Crop models > *Where crops are downloaded from*. The value is stored in
`<documents>/packs/catalog_url` and survives app updates. This exists because a
build-time-only constant means a handset pointed at a host that later goes away
can never be recovered without reinstalling, which is not something you can ask
a farmer to do.

**Or set the default at build time:**

```bash
flutter build apk --release   --dart-define=PACK_CATALOG_BASE=https://your-bucket.example.com/packs
```

The default in `app/lib/packs/pack_store.dart` is
`https://packs.cropguard.in/packs`, which **does not exist yet**. Until that
bucket is real, every build needs the `--dart-define` above or the crop picker
will show "Could not get the crop list".

To try it without a bucket at all, serve `dist/` from your machine and point
the handset at it over the same wifi:

```bash
python -m http.server 8099 --bind 0.0.0.0     # from dist/
ipconfig                                       # note the LAN address
```

Then set `http://<your-lan-ip>:8099/packs` in Menu > Crop models. Over USB,
`adb reverse tcp:8099 tcp:8099` and `http://127.0.0.1:8099/packs` works too.

Plain HTTP is fine for either: `network_security_config.xml` governs the
**WebView** (which is why loopback is listed there — the bundled UI loads from
`http://127.0.0.1:<port>`), but pack downloads go through Dart's `dart:io`
sockets, which Android's cleartext policy does not apply to. Use HTTPS in
production regardless; the manifest will not stop you either way, and the
payload is a table of pesticide doses.

### Two kinds of pack

| | `crop` | `detector` |
|---|---|---|
| Example | `potato` | `croprow`, `crophealth` |
| Contents | model, thresholds, taxonomy, strings, KB pages | model, thresholds, taxonomy |
| Drives | photo diagnosis, triage, treatment advice | one lab scanner |
| Size | ~45 MB | ~11 MB |

A crop pack without its KB pages is a bug: it could diagnose and never advise.
A detector pack without them is correct, because a box drawn around a lettuce
is not advice and must not be dressed up as any.

The distinction is load-bearing in one specific place. `activePack()` — what
`/detect` serves the farmer from — considers **crop packs only**. Without that,
installing Crop row scan would repoint the potato scanner at a single-class
lettuce localiser, and it would return boxes labelled "lettuce" with no error
anywhere. `pack_store_test.dart` pins it both ways: a detector never becomes
active, and a detector installed alone leaves the crop scanner reporting
nothing rather than reporting a lettuce.

The lab endpoints also answer in a **different shape** from the potato ones:
`/croprow/status` returns `available`, `/detect/status` returns
`model_available`. That is not tidy, but the pages were written against the
server's shapes and quietly renaming a key here reads as "no model installed"
with nothing in any log.

### What the installer refuses

Every file is checked against the SHA-256 in the manifest, the whole set is
staged in a temporary directory, and only then moved into place. A pack that
fails any check leaves nothing behind. This is not ceremony: the payload is a
table of pesticide doses, and TLS protects the transport, not a compromised
bucket or a wrong upload. `app/test/pack_store_test.dart` asserts each refusal
against a real HTTP server — corrupted byte, truncated body, wrong crop in the
manifest, `min_app_version` above this build.

Packs install into the app documents directory, never the cache directory:
Android evicts cache under storage pressure, and a pack that vanished mid-season
would break offline use precisely when the farmer cannot re-download it.

## File inputs need the host's help

Android's WebView does not open a file chooser on its own. It asks the host app
through `onShowFileChooser`, and a host that does not answer leaves the tap
**silently dead** - no picker, no error, no console message, nothing in logcat.
`main.dart` answers it via `setOnShowFileSelector`.

This is worth knowing because the failure is invisible from the web side. Every
`<input type="file">` in the bundled UI depends on it: video upload on both lab
scanners, and the photo picker on Check crop. All three looked like a UI bug
and none of them were.

The handler narrows the picker to what the input asked for - `accept="video/*"`
opens videos, not a photo grid - because a farmer picking a still that the clip
scanner then refuses is a worse experience than no picker at all.

One dependency note: `file_picker` pulls in `flutter_plugin_android_lifecycle`,
whose 2.0.35 demands consumers compile against API 36 while `file_picker`
itself still compiles against 34 - a skew inside the plugin's own dependency
tree. `pubspec.yaml` pins the older lifecycle plugin in `dependency_overrides`.
The alternative, forcing every plugin module's `compileSdk` from the root Gradle
script, has to fight Gradle's evaluation order and did not work.

## Where inference actually runs

There is no ONNX runtime in the app's Dart process, and there is no server to
upload a photograph to. There is, however, one already in the WebView, fetching
these same weights for the live scanner — so the page runs the model itself.

`/detect/status` advertises this with `inference: "in_page"`. The web
deployment has no such key, so it keeps uploading to the backend and nothing
about it changes. `frontend/src/lib/detectPhoto.js` is the one seam: it takes
the FormData the upload path already builds, and either posts it or decodes the
image, runs the session and asks the local API only for the parts it cannot
compute — the triage gate and the advisory, both of which are offline anyway.

The alternative was a farmer standing in a field being told to find a network
connection for a diagnosis their phone could already do, with the model
downloaded and sitting on disk. `POST /api/detect` on the handset therefore
never says "needs a network connection": with no pack it says which crop to
install, and that is not a network problem.

## Offline advisory (RAG)

Retrieval runs on the handset, over the KB pages in the installed pack. There is
no vector backend and no embedding model — BM25 is the implementation, not a
fallback. That is an honest fit rather than a compromise: the corpus is six
markdown pages, the query is a class key plus a few field terms, and the
retrieval unit is a markdown section.

It is also not hand-waved. `app/lib/kb/knowledge_base.dart` is a port of the
Python retriever, and `mobileapp/fixtures/kb.json` pins the tokenizer, the
chunking and the BM25 scores so the same question gives a farmer and an officer
the same dose table. Porting it surfaced one real difference: Python's
`list.sort` is stable and Dart's is not, so tied chunks came back in a different
order until the Dart side broke ties on corpus index.

Doses are **parsed** out of the reviewed markdown tables, never generated. The
numbers a farmer sprays by stay accountable to a file an agronomist can correct
in a pull request — which matters more on a handset, not less, because there is
nobody there to catch a hallucinated dose.

## Demonstration data on the handset

```bash
python mobileapp/tools/export_demo_dataset.py --write
python mobileapp/tools/export_demo_dataset.py --check   # CI guard
```

Writes `app/assets/demo/dataset.json` (~290 KB): 120 cases, 120 follow-ups and
520 trap readings across the Maharashtra potato districts. The app derives the
dashboard, the hotspot cells, the review queue and the follow-up statistics from
those rows, so the period selector and the district filter genuinely filter
rather than moving four fixed numbers.

Two properties worth knowing:

* **Records store day offsets, not timestamps**, and the dates are materialised
  against the clock when the asset loads. A fixed timestamp would mean an APK
  built in September shows September cases at Christmas, with an empty "last 7
  days" window.
* **It is never passed off as real.** Every record carries `demo: true`, farmer
  names start "Demo" and the model version is `demo-seed`. The UI's existing
  "Demo + live / Live only" toggle drives it: `include_demo=false` returns
  genuinely empty results, because this device holds no other farmers' cases
  until it syncs.

## Fixtures

```bash
python mobileapp/tools/export_fixtures.py --check    # verify (CI)
python mobileapp/tools/export_fixtures.py --write    # regenerate
```

These pin the behaviour of the Python domain services so the Dart port can be
held to the same numbers. Read [`fixtures/FORMAT.md`](fixtures/FORMAT.md)
before adding a case — particularly the rule that a failing `--check` is read,
not regenerated away.

## Crop packs

A crop is a **downloadable pack**, not an app release. The unit is:

```
packs/<crop>@<version>/
  model.onnx        quantised detector
  thresholds.json   per-class cut-offs, tuned for THIS quantised file
  taxonomy.json     class list, threat keys, crop-stage factors
  kb/*.md           disease pages, including the dose tables
  strings.json      mr/hi/bn/en advisory strings for this crop
  manifest.json     version, per-file SHA-256, min_app_version, signature
```

Weights alone are not a pack. A model that predicts `tomato_late_blight` with
no dose table, no Marathi string and no taxonomy entry produces a diagnosis the
app cannot safely advise on — which, given the safety gating, is worse than
not supporting the crop at all.

Three rules that fall out of that:

* **Thresholds and weights version together, atomically.** Mixing a
  re-quantised model with the previous threshold file is a silent accuracy
  regression no test catches and no farmer reports.
* **Packs are signed and hash-verified**, and installed atomically
  (download → verify → swap). The payload contains pesticide doses; TLS
  protects the transport, not a compromised bucket or a wrong upload.
* **Every crop is downloaded, including potato.** An earlier draft of this
  document had potato shipping inside the APK. It does not: bundling it would
  add ~45 MB to every install and, worse, would leave the download-verify-swap
  path as a rarely-exercised branch that first runs in anger the day a second
  crop ships. One code path, used from the first launch, is the safer trade.
  The cost is that first launch needs a connection once, which the crop picker
  says plainly and allows you to skip — risk forecasting works without a pack.

Packs live in the app documents directory, never the cache directory — Android
evicts cache under storage pressure, which would silently break offline use.

## Open questions for the team

Two findings from pinning the triage branches. Both are judgement calls about
safety behaviour, so they are recorded rather than changed:

1. **`conflicting_signals` escalates but still permits self-treatment**, at
   `routine` urgency. The reason text says *"the wrong product here wastes
   money and leaves residue for no benefit"* — yet
   `self_treatment_allowed` stays `true`, so nothing stops the farmer acting
   on the disputed diagnosis. Compare `low_confidence`, which sets it `false`
   for a weaker reason to doubt the label.

2. **`high_severity` escalates to district at `urgent` but also leaves
   `self_treatment_allowed` true.** This one is arguably right — telling a
   farmer with 70% of the field affected to do nothing until an officer
   arrives is its own harm — but it should be a decision on the record, not a
   consequence of rule 7 not setting the flag.

Whatever is decided, the fixtures make the answer visible and keep Dart and
Python agreeing on it.
