# CropGuard — Flutter app

The Android app for farmers. It hosts the CropGuard React UI in a WebView and
answers its API calls from an on-device Dart server, so the farmer loop runs
offline.

| Path | What |
|---|---|
| `lib/main.dart` | Shell: WebView host, camera permission, file-chooser bridge, boot sequence |
| `lib/local_server.dart` | The offline backend: static assets + the whole `/api` surface |
| `lib/domain/` | Weather, risk models, triage, taxonomy, geo (ported from `backend/app/services/`) |
| `lib/kb/` | BM25 retriever and advisory composer |
| `lib/packs/` | Crop pack model, download/verify/install, first-launch crop picker |
| `lib/demo/` | Bundled demo dataset behind the officer screens |
| `test/` | `flutter test` — golden vectors, pack store, API contract, offline engine |

`assets/web/` is build output: run `pwsh ../tools/stage_web.ps1` after any
frontend change, before building.

```bash
flutter pub get
flutter test
flutter build apk --release --dart-define=PACK_CATALOG_BASE=https://<host>/packs
```

Everything else — architecture, API surface, Android pitfalls, troubleshooting —
is in [`../mobileapp.md`](../mobileapp.md) and [`../README.md`](../README.md).
