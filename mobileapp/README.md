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
| 1. Golden-vector fixtures | **done** — 83 cases across geo, risk models, triage |
| 2. `cropguard_domain` Dart package | not started |
| 3. Drift schema, UUID ids, outbox | not started |
| 4. Detection (ORT Mobile + Dart decoder) | not started |
| 5. Advisory (KB assets, Dart BM25) | not started |
| 6. Farmer UI | not started |
| 7. Sync worker + digest endpoint | not started |
| 8. Weather prefetch | not started |

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
* **Potato ships inside the APK** and is copied into `packs/` on first launch,
  so it is updatable through the same path as any downloaded crop rather than
  being a permanent special case.

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
