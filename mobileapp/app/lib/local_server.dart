/// The offline backend.
///
/// Serves the bundled CropGuard UI and implements the `/api` surface it calls,
/// entirely on `127.0.0.1` inside the app process. Nothing here touches the
/// network, so the whole thing works in airplane mode.
///
/// What is real and what is not, stated plainly because the rest of this
/// project is careful about that distinction:
///
///   REAL, on-device   the published agronomic models (Smith, Beaumont,
///                     TOMCAST, degree-days), the deterministic weather feed
///                     they run on, the triage safety gate, and the class
///                     taxonomy. All validated against the Python golden
///                     vectors in mobileapp/fixtures.
///
///   NOT AVAILABLE     image detection - no model is bundled in this build, so
///                     /detect/status reports unavailable and cases route to
///                     the expert queue rather than returning a guess.
///
///   ONLINE-ONLY       cross-farm outbreak pressure, the hotspot map, the
///                     officer dashboard and the review queue. These need
///                     other farmers' cases by definition. They return empty
///                     rather than fabricating rows.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart' show rootBundle;

import 'demo/demo_api.dart';
import 'demo/demo_dataset.dart';
import 'domain/geo.dart';
import 'domain/risk_models.dart';
import 'domain/taxonomy.dart';
import 'domain/triage.dart';
import 'domain/weather.dart';
import 'kb/advisory.dart';
import 'kb/knowledge_base.dart';
import 'packs/pack.dart';
import 'packs/pack_store.dart';

const String _assetRoot = 'assets/web';

/// Mirrors `UNVERIFIED_WEIGHT` and `INTENSITY_BANDS['severe']` in
/// backend/app/routers/hotspots.py. The map renders both, so they have to be
/// the same numbers the server would have sent.
const double kUnverifiedWeight = 0.4;
const double kSevereThreshold = 8.0;

class LocalServer {
  HttpServer? _server;

  DemoApi? _demo;
  KnowledgeBase? _kb;
  String? _kbPackKey;

  /// In-flight pack install, if any.
  ///
  /// A 45 MB download takes a minute or more on a rural connection, so the
  /// install runs in the background and the UI polls. Holding the HTTP request
  /// open for the whole transfer would give the page a choice between a dead
  /// spinner and a timeout, and neither tells the farmer whether to keep
  /// waiting.
  Map<String, dynamic>? _install;

  bool get _installRunning => _install?['active'] == true;

  /// The demo dataset, parsed once. 120 cases is nothing to hold, and
  /// re-parsing 293 KB of JSON per request would be visible on a cheap handset.
  Future<DemoApi> _demoApi() async {
    return _demo ??= DemoApi(await DemoDataset.load());
  }

  /// The retriever over the active pack's KB pages, rebuilt only when the pack
  /// changes. Indexing is cheap but not free, and it is not per-query work.
  Future<KnowledgeBase?> _knowledgeBase() async {
    final pack = await PackStore.instance.activePack();
    if (pack == null) return null;
    final key = '${pack.crop}@${pack.version}';
    if (_kb != null && _kbPackKey == key) return _kb;
    final docs = <String, String>{};
    for (final f in pack.manifest.files) {
      if (!f.path.startsWith('kb/') || !f.path.endsWith('.md')) continue;
      final text = await PackStore.instance.readString(pack, f.path);
      if (text != null) docs[f.path.substring(3)] = text;
    }
    _kbPackKey = key;
    return _kb = KnowledgeBase.fromDocuments(docs);
  }

  /// Shared instance - the WebView needs the origin, and the origin is not
  /// known until the OS assigns a port.
  static final LocalServer instance = LocalServer();

  /// The origin the WebView should load, e.g. http://127.0.0.1:53217
  String get origin => 'http://127.0.0.1:${_server!.port}';

  Future<String> start() async {
    // Port 0 = let the OS pick a free one. A fixed port collides with whatever
    // else the handset happens to be running.
    _server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server!.listen(_handle, onError: (Object e) {});
    return origin;
  }

  Future<void> stop() async {
    await _server?.close(force: true);
    _server = null;
  }

  Future<void> _handle(HttpRequest req) async {
    try {
      final path = req.uri.path;
      if (path == '/api' || path.startsWith('/api/')) {
        await _api(req, path.replaceFirst('/api', ''));
      } else {
        await _static(req, path);
      }
    } catch (e) {
      await _json(req, {'detail': 'Internal error: $e'}, status: 500);
    }
  }

  // ------------------------------------------------------------------
  // Static assets, read straight out of the APK
  // ------------------------------------------------------------------
  Future<void> _static(HttpRequest req, String path) async {
    var rel = path == '/' ? '/index.html' : path;
    if (rel.startsWith('/')) rel = rel.substring(1);

    try {
      final data = await rootBundle.load('$_assetRoot/$rel');
      req.response
        ..statusCode = 200
        ..headers.contentType = _mime(rel)
        // The bundle is immutable for the life of an install.
        ..headers.set('Cache-Control', 'public, max-age=31536000, immutable')
        ..add(data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
      await req.response.close();
    } catch (_) {
      // Unknown path. Client-side routing needs a deep link or a refresh to
      // return index.html - but ONLY for navigation. Handing index.html back
      // for a missing asset turns a 404 into a 200 full of HTML, and the
      // browser then reports whatever confused thing it makes of that.
      //
      // This cost an afternoon: a missing ONNX runtime module came back as
      // "Expected a JavaScript-or-Wasm module script but the server responded
      // with a MIME type of text/html", which reads like a server
      // misconfiguration rather than a file we forgot to ship.
      if (_looksLikeAsset(rel)) {
        req.response.statusCode = 404;
        await req.response.close();
        return;
      }
      try {
        final idx = await rootBundle.load('$_assetRoot/index.html');
        req.response
          ..statusCode = 200
          ..headers.contentType = ContentType.html
          ..add(idx.buffer.asUint8List(idx.offsetInBytes, idx.lengthInBytes));
        await req.response.close();
      } catch (_) {
        req.response.statusCode = 404;
        await req.response.close();
      }
    }
  }

  /// A path a browser fetches as a resource rather than navigates to. Anything
  /// with a file extension we recognise is a resource; a route like
  /// `/dashboard` or `/models` is not.
  static final RegExp _assetExt = RegExp(
    r'\.(js|mjs|css|json|wasm|map|png|jpe?g|svg|gif|webp|ico|woff2?|ttf|otf|txt|onnx|md)$',
    caseSensitive: false,
  );

  bool _looksLikeAsset(String rel) => _assetExt.hasMatch(rel);

  ContentType _mime(String p) {
    if (p.endsWith('.html')) return ContentType.html;
    if (p.endsWith('.js') || p.endsWith('.mjs')) {
      return ContentType('text', 'javascript', charset: 'utf-8');
    }
    if (p.endsWith('.css')) return ContentType('text', 'css', charset: 'utf-8');
    if (p.endsWith('.json')) return ContentType.json;
    if (p.endsWith('.wasm')) return ContentType('application', 'wasm');
    if (p.endsWith('.svg')) return ContentType('image', 'svg+xml');
    if (p.endsWith('.png')) return ContentType('image', 'png');
    if (p.endsWith('.jpg') || p.endsWith('.jpeg')) {
      return ContentType('image', 'jpeg');
    }
    if (p.endsWith('.wasm.map') || p.endsWith('.map')) return ContentType.json;
    return ContentType.binary;
  }

  Future<void> _json(HttpRequest req, Object body, {int status = 200}) async {
    req.response
      ..statusCode = status
      ..headers.contentType = ContentType.json
      ..write(jsonEncode(body));
    await req.response.close();
  }

  // ------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------
  Future<void> _api(HttpRequest req, String path) async {
    final q = req.uri.queryParameters;
    double? d(String k) => double.tryParse(q[k] ?? '');

    switch (path) {
      case '/meta/health':
        return _json(req, _health());
      case '/meta/classes':
        return _json(req, {
          'crop': kCrop,
          'classes': kClasses.map((c) => c.toJson()).toList(),
          'non_model_threats': kNonModelThreats,
        });
      case '/meta/languages':
        return _json(req, {
          'languages': [
            {'code': 'en', 'name': 'English'},
            {'code': 'mr', 'name': 'मराठी (Marathi)'},
            {'code': 'hi', 'name': 'हिन्दी (Hindi)'},
            {'code': 'bn', 'name': 'বাংলা (Bengali)'},
          ],
        });

      case '/home/overview':
        return _json(req, _overview(d('latitude') ?? 18.52, d('longitude') ?? 73.86));

      case '/risk':
      case '/risk/':
        final body = await _body(req);
        return _json(
            req,
            _risk(
              (body['latitude'] as num?)?.toDouble() ?? d('latitude') ?? 18.52,
              (body['longitude'] as num?)?.toDouble() ?? d('longitude') ?? 73.86,
            ));

      case '/risk/weather':
        final s = getSeries(lat: d('latitude') ?? 18.52, lon: d('longitude') ?? 73.86);
        return _json(req, s.toJson());

      case '/risk/models':
        return _json(req, {
          'models': [
            {
              'key': 'smith_period',
              'name': 'Smith Period',
              'threat': 'potato_late_blight',
              'citation': 'Smith (1956); UK MAFF criteria',
            },
            {
              'key': 'beaumont_period',
              'name': 'Beaumont Period',
              'threat': 'potato_late_blight',
              'citation': 'Beaumont (1947)',
            },
            {
              'key': 'tomcast_dsv',
              'name': 'TOMCAST DSV',
              'threat': 'potato_early_blight',
              'citation': 'Pitblado; Madden/Pennypacker severity values',
            },
            {
              'key': 'degree_days',
              'name': 'Growing degree-days',
              'threat': 'potato_tuber_moth',
              'citation': 'Single-triangle base-temperature method',
            },
          ],
        });

      // Detection comes from the installed crop pack. No pack, no detector -
      // and that is reported rather than guessed around, because a confident
      // wrong class is worse than an admitted absence.
      case '/detect/status':
        return _json(req, await _detectStatus());

      // The lab scanners, each from its own detector pack.
      case '/croprow/status':
        return _json(req, await _detectorStatus('croprow', 'Crop row scan'));
      case '/crophealth/status':
        return _json(req, await _detectorStatus('crophealth', 'Crop health scan'));

      case '/detect/thresholds':
        return _json(req, await _detectThresholds());

      case '/croprow/thresholds':
        return _json(req, await _detectorThresholds('croprow'));
      case '/crophealth/thresholds':
        return _json(req, await _detectorThresholds('crophealth'));

      case '/croprow/model':
        return _serveDetectorModel(req, 'croprow');
      case '/crophealth/model':
        return _serveDetectorModel(req, 'crophealth');

      // The weights themselves, straight off disk. This is what makes the
      // in-WebView ONNX scanner work with the radio off: the page fetches this
      // URL exactly as it would fetch it from the server.
      case '/detect/model':
        return _serveModel(req);

      // The photo upload path. This build cannot run it: inference happens in
      // the page, which reads `inference: in_page` from /detect/status and
      // never posts here. Anything that does reach this deserves a reason, not
      // the generic "needs a network connection" - it is not a network problem
      // and telling a farmer to find signal would waste their afternoon.
      case '/detect':
      case '/detect/frame':
        {
          final pack = await PackStore.instance.activePack();
          return _json(req, {
            'detail': pack == null
                ? 'No crop pack is installed, so this photograph cannot be '
                    'diagnosed on this phone. Install a crop from Menu > Crop '
                    'models, then try again. This is not a network problem.'
                : 'This build runs detection inside the app rather than on a '
                    'server. If you are seeing this, reload the app.',
            'model_available': pack != null,
          }, status: 503);
        }

      // ----------------------------------------------------------------
      // Advisory - retrieval-augmented, entirely on-device.
      //
      // BM25 over the installed pack's KB pages. No embedding model, no vector
      // store, no network: the corpus is six markdown pages of agronomy and the
      // queries are a class key plus a handful of field terms, which is exactly
      // the shape lexical retrieval is good at. The scores are held to the
      // Python service's by mobileapp/fixtures/kb.json.
      // ----------------------------------------------------------------
      case '/advisory/status':
        {
          final kb = await _knowledgeBase();
          final pack = await PackStore.instance.activePack();
          return _json(req, {
            'backend': kb == null ? 'unavailable' : 'lexical-bm25',
            'documents': kb == null
                ? 0
                : kb.chunks.map((c) => c.docId).toSet().length,
            'chunks': kb?.chunks.length ?? 0,
            'pack': pack == null ? null : '${pack.crop}@${pack.version}',
            'offline': true,
            'note': kb == null
                ? 'No crop pack is installed, so there is no knowledge base to '
                    'search. Install a crop first.'
                : 'Retrieval runs on this device. There is no vector backend '
                    'on a handset, so BM25 is the implementation rather than a '
                    'fallback.',
          });
        }

      case '/advisory/search':
        {
          final kb = await _knowledgeBase();
          final query = q['q'] ?? '';
          if (kb == null) {
            return _json(req, {
              'detail': 'No crop pack is installed, so there is nothing to '
                  'search yet.'
            }, status: 404);
          }
          final classFilter = q['class_key'] == null || q['class_key']!.isEmpty
              ? null
              : [q['class_key']!];
          return _json(req, {
            'query': query,
            'backend': 'lexical-bm25',
            'hits': kb.search(query, k: _int(q['k'], 5), classFilter: classFilter),
            'offline': true,
          });
        }

      case '/advisory':
        {
          final body = await _body(req);
          return _json(req, await _advisory(body));
        }

      // ----------------------------------------------------------------
      // Crop packs
      // ----------------------------------------------------------------
      case '/packs/installed':
        {
          final packs = await PackStore.instance.installed();
          final active = await PackStore.instance.activePack();
          return _json(req, {
            'installed': [
              for (final p in packs)
                {
                  'crop': p.crop,
                  'kind': p.manifest.kind,
                  'title': p.manifest.title,
                  'version': p.version,
                  'classes': p.manifest.classes,
                  'total_bytes': p.manifest.totalBytes,
                  'built_at': p.manifest.builtAt,
                  'active': active != null && active.crop == p.crop,
                }
            ],
            'active': active == null ? null : '${active.crop}@${active.version}',
          });
        }

      // The catalogue, proxied through the local API so the web UI can offer
      // crop management too rather than it living only in the first-launch
      // Flutter screen.
      // Where this handset looks for crops. Settable at runtime: a build
      // pointed at a host that later goes away must be recoverable without
      // reinstalling the app.
      case '/packs/source':
        {
          if (req.method == 'POST') {
            final body = await _body(req);
            await PackStore.instance.setCatalogBase(body['url'] as String?);
          }
          return _json(req, {
            'url': await PackStore.instance.catalogBase(),
            'compiled_default': kPackCatalogBase,
          });
        }

      case '/packs/catalog':
        {
          try {
            final crops = await PackStore.instance.catalog();
            return await _json(req, {
              'crops': [
                for (final c in crops)
                  {
                    'crop': c.crop,
                    'kind': c.kind,
                    'title': c.title,
                    'latest': c.latest,
                    'versions': [
                      for (final v in c.versions)
                        {
                          'version': v.version,
                          'total_bytes': v.totalBytes,
                          'min_app_version': v.minAppVersion,
                          'classes': v.classes,
                        }
                    ],
                  }
              ],
            });
          } on PackException catch (e) {
            // This is the one call that needs a connection, so a failure here
            // is expected offline rather than exceptional.
            return _json(req, {'detail': e.message}, status: 503);
          }
        }

      case '/packs/install':
        {
          // Validate the request before reporting on server state: a
          // malformed body is malformed whether or not something else is
          // running, and answering 409 to it sends the caller to retry a
          // request that will never work.
          final body = await _body(req);
          final cropKey = body['crop'] as String?;
          if (cropKey == null) {
            return _json(req, {'detail': 'crop is required'}, status: 400);
          }
          if (_installRunning) {
            return _json(req, {
              'detail': 'An install is already running.',
              'progress': _install,
            }, status: 409);
          }
          final wanted = body['version'] as String?;
          // Kick it off and answer immediately; /packs/progress carries the
          // rest. Errors land in the progress record rather than on a request
          // nobody is waiting on any more.
          unawaited(_runInstall(cropKey, wanted));
          return _json(req, {
            'started': true,
            'crop': cropKey,
            'version': wanted,
          }, status: 202);
        }

      case '/packs/progress':
        return _json(
            req,
            _install ??
                {
                  'active': false,
                  'phase': 'idle',
                  'received_bytes': 0,
                  'total_bytes': 0,
                });

      case '/chat/status':
        return _json(req, {
          'mode': 'offline',
          'note': 'The assistant needs a network connection. Advisories, risk '
              'forecasts and diagnosis guidance all work offline.',
        });

      // The officer views - dashboard, hotspot map, review queue - have two
      // honest answers offline, and which one you get is the farmer's choice,
      // not ours.
      //
      // `include_demo=true` (the UI's "Demo + live" toggle, and the default)
      // serves the synthetic dataset bundled in the APK. Nothing about it is
      // presented as real: every row carries `demo: true`, farmer names start
      // "Demo" and the model version is `demo-seed`.
      //
      // `include_demo=false` serves genuinely empty results, because this
      // device holds no other farmers' cases until it syncs.
      //
      // Either way the SHAPE is the server's. The UI reads these payloads
      // positionally - `summary.cases.total`, `rows.find(...)` - so an
      // `{items: [], offline: true}` envelope is not a softer failure than a
      // 500, it is a harder one: the read throws during render, React unmounts
      // the tree and the farmer gets a white screen with no way back.
      case '/hotspots':
        {
          final days = _int(q['days'], 30);
          final cell =
              double.tryParse(q['cell_size_deg'] ?? '') ?? kDefaultCellDeg;
          if (_includeDemo(q)) {
            return _json(
                req, (await _demoApi()).hotspots(days, cell, q['district']));
          }
          // The map prints `data.total_confirmed` and `data.unverified_weight`
          // straight into its caption, so a short payload here does not crash -
          // it renders the literal text "undefined confirmed - undefined
          // pending". Quieter than a white screen and just as wrong.
          return _json(req, {
            'window_days': days,
            'cell_size_deg': cell,
            'unverified_weight': kUnverifiedWeight,
            'total_cells': 0,
            'total_confirmed': 0,
            'total_unverified': 0,
            'cells': const [],
            'offline': true,
          });
        }

      case '/hotspots/points':
        {
          final days = _int(q['days'], 30);
          if (_includeDemo(q)) {
            return _json(
                req, (await _demoApi()).hotspotPoints(days, q['district']));
          }
          return _json(req, {
            'window_days': days,
            'unverified_weight': kUnverifiedWeight,
            // The heat ramp's top of scale. Falling back to the client default
            // would quietly re-scale the map the moment sync fills it in.
            'severe_threshold': kSevereThreshold,
            'total_confirmed': 0,
            'total_unverified': 0,
            'total_points': 0,
            'points': const [],
            'offline': true,
          });
        }

      // list[CaseOut] / list[FollowUpOut] / list[SensorReadingOut] - JSON
      // arrays on the server, so arrays here.
      case '/review/queue':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi()).reviewQueue(
                    limit: _int(q['limit'], 60),
                    onlyEscalated: q['only_escalated'] == 'true',
                  )
                : const []);

      case '/dashboard/cases':
        return _json(req, const []);

      case '/followups':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi()).followUps(limit: _int(q['limit'], 100))
                : const []);

      case '/sensors':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi()).sensors(limit: _int(q['limit'], 200))
                : const []);

      case '/dashboard/summary':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi())
                    .dashboardSummary(_int(q['days'], 30), q['district'])
                : _dashboardSummary(_int(q['days'], 30), q['district']));

      case '/dashboard/trend':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi()).dashboardTrend(
                    _int(q['days'], 30), q['district'], q['class_key'])
                : _dashboardTrend(_int(q['days'], 30), q['class_key']));

      case '/dashboard/districts':
        return _json(
            req,
            _includeDemo(q)
                ? (await _demoApi()).dashboardDistricts()
                : {'districts': const [], 'offline': true});

      case '/review/stats/accuracy':
        if (_includeDemo(q)) return _json(req, (await _demoApi()).accuracy());
        return _json(req, {
          'reviewed': 0,
          'confirmed': 0,
          'corrected': 0,
          'rejected': 0,
          'pending': 0,
          'field_accuracy': null,
          'per_class': [],
          'retraining_samples_pending_export': 0,
          'offline': true,
        });

      case '/followups/stats':
        if (_includeDemo(q)) {
          return _json(req, (await _demoApi()).followUpStats(_int(q['days'], 90)));
        }
        return _json(req, {
          'window_days': _int(q['days'], 90),
          'counts': const <String, int>{},
          'closed': 0,
          'overdue': 0,
          'improvement_rate': null,
          'offline': true,
        });

      case '/sensors/summary':
        if (_includeDemo(q)) {
          return _json(
              req,
              (await _demoApi()).sensorSummary(
                  _int(q['days'], 14), q['metric'] ?? 'trap_count'));
        }
        return _json(req, {
          'metric': q['metric'] ?? 'trap_count',
          'window_days': _int(q['days'], 14),
          'cells': const [],
          'offline': true,
        });
    }

    return _json(req, {
      'detail': 'This feature needs a network connection and is not available '
          'in the offline build.'
    }, status: 503);
  }

  int _int(String? raw, int fallback) => int.tryParse(raw ?? '') ?? fallback;

  /// `true` unless the caller explicitly asked for live-only. Mirrors the
  /// server's `include_demo` default and the UI's "Demo + live" toggle.
  bool _includeDemo(Map<String, String> q) {
    final raw = q['include_demo'];
    if (raw == null) return true;
    return !(raw == 'false' || raw == '0');
  }

  Future<void> _runInstall(String cropKey, String? wanted) async {
    _install = {
      'active': true,
      'crop': cropKey,
      'version': wanted,
      'phase': 'catalog',
      'received_bytes': 0,
      'total_bytes': 0,
      'file': '',
      'error': null,
    };
    try {
      final crops = await PackStore.instance.catalog();
      final crop = crops.firstWhere(
        (c) => c.crop == cropKey,
        orElse: () => throw PackException('No crop $cropKey in the catalogue.'),
      );
      final version = wanted == null
          ? crop.latestVersion
          : crop.versions.firstWhere(
              (v) => v.version == wanted,
              orElse: () => throw PackException('No version $wanted for $cropKey.'),
            );
      if (version == null) {
        throw PackException('No version available for $cropKey.');
      }
      final installed = await PackStore.instance.install(
        crop,
        version,
        onProgress: (p) {
          _install = {
            'active': true,
            'crop': cropKey,
            'version': version.version,
            'phase': p.phase,
            'received_bytes': p.receivedBytes,
            'total_bytes': p.totalBytes,
            'file': p.file,
            'error': null,
          };
        },
      );
      // The KB is indexed per pack, so a new install must invalidate it or the
      // advisory would keep answering from the previous crop.
      _kb = null;
      _kbPackKey = null;
      _install = {
        'active': false,
        'crop': installed.crop,
        'version': installed.version,
        'phase': 'done',
        'received_bytes': installed.manifest.totalBytes,
        'total_bytes': installed.manifest.totalBytes,
        'file': '',
        'error': null,
      };
    } catch (e) {
      _install = {
        'active': false,
        'crop': cropKey,
        'version': wanted,
        'phase': 'failed',
        'received_bytes': 0,
        'total_bytes': 0,
        'file': '',
        'error': '$e',
      };
    }
  }

  /// `POST /api/advisory` - retrieval, composition, safety gate, all on-device.
  Future<Map<String, dynamic>> _advisory(Map<String, dynamic> body) async {
    final kb = await _knowledgeBase();
    final pack = await PackStore.instance.activePack();
    final lang = (body['language'] as String?) ?? 'en';
    final classKey = body['class_key'] as String?;
    final confidence = (body['confidence'] as num?)?.toDouble();

    final lat = (body['latitude'] as num?)?.toDouble() ?? 18.52;
    final lon = (body['longitude'] as num?)?.toDouble() ?? 73.86;
    final risk = _risk(lat, lon);

    // A caller that names a class is reporting a detection. Leaving
    // detectionCount at 0 made triage fire `no_detection` on every advisory,
    // which set self_treatment_allowed false and withheld the dose table for a
    // confidently diagnosed case - the safety gate firing on its own default.
    final hasDetection = classKey != null && classKey.isNotEmpty;
    final triage = evaluateTriage(
      modelAvailable: pack != null,
      predictedClass: classKey,
      confidence: confidence,
      detectionCount: hasDetection ? 1 : 0,
      risk: {
        'top_threat': risk['top_threat'],
        'overall_level': risk['overall_level'],
      },
    ).toJson();

    if (kb == null) {
      // No pack, so no knowledge base and no dose tables. Say that plainly
      // rather than composing an advisory with an empty treatment section,
      // which reads as "nothing to do".
      return {
        'advisory': null,
        'triage': triage,
        'risk': risk,
        'language': lang,
        'detail': 'No crop pack is installed, so there is no knowledge base to '
            'advise from. Install a crop to get treatment guidance offline.',
        'offline': true,
      };
    }

    final stringsRaw = await PackStore.instance.readString(pack!, 'strings.json');
    final strings = AdvisoryStrings.fromPackJson(
      stringsRaw == null
          ? const {}
          : jsonDecode(stringsRaw) as Map<String, dynamic>,
    );
    final classNames = stringsRaw == null
        ? const <String, dynamic>{}
        : ((jsonDecode(stringsRaw) as Map<String, dynamic>)['classes'] as Map?)
                ?.cast<String, dynamic>() ??
            const <String, dynamic>{};

    String displayFor(String key, String l) {
      final byLang = (classNames[l] as Map?)?.cast<String, dynamic>();
      // Pack names first, then the app's built-in taxonomy: a downloaded crop
      // must be able to name classes this app release has never heard of.
      return (byLang?[key] as String?) ?? displayName(key, l);
    }

    final advisory = composeAdvisory(
      input: AdvisoryInput(
        classKey: classKey,
        language: lang,
        confidence: confidence,
        question: body['question'] as String?,
        risk: risk,
        triage: triage,
        modelAvailable: true,
        hasDetection: hasDetection,
      ),
      kb: kb,
      strings: strings,
      displayFor: displayFor,
    );

    return {
      'advisory': advisory,
      'triage': triage,
      'risk': (body['include_risk'] as bool? ?? false) ? risk : null,
      'language': lang,
      'offline': true,
    };
  }

  Future<Map<String, dynamic>> _detectStatus() async {
    final pack = await PackStore.instance.activePack();
    if (pack == null) {
      return {
        'model_available': false,
        'model_version': null,
        'classes': kClassNames,
        'inference': 'in_page',
        'note': 'No crop pack is installed, so photographs are routed to the '
            'expert queue instead of being guessed at. Install a crop to '
            'enable on-device detection.',
      };
    }
    return {
      'model_available': true,
      'model_version': '${pack.crop}@${pack.version}',
      'classes': pack.manifest.classes,
      'crop': pack.crop,
      'pack_version': pack.version,
      // Tells the page to run inference itself rather than POSTing the photo.
      // There is no ONNX runtime in this Dart process, but there is one in the
      // WebView, already fetching these same weights for the live scanner. The
      // server build has no such key, so the page keeps uploading there.
      'inference': 'in_page',
      'note': 'Detection runs in this app, on this device, from the installed '
          '${pack.crop} pack.',
    };
  }

  Future<Map<String, dynamic>> _detectThresholds() async {
    final pack = await PackStore.instance.activePack();
    if (pack == null) return {'default': 0.25, 'per_class': const {}};
    final raw = await PackStore.instance.readString(pack, 'thresholds.json');
    if (raw == null) return {'default': 0.25, 'per_class': const {}};
    try {
      final parsed = jsonDecode(raw) as Map<String, dynamic>;
      // Thresholds are tuned for THIS pack's weights. Passing them through
      // unchanged is the point; reshaping or defaulting them here would be the
      // silent accuracy regression the pack format exists to prevent.
      return {
        'classes': parsed['classes'] ?? pack.manifest.classes,
        'per_class': parsed['per_class'] ?? parsed['conf_thresholds'] ?? const {},
        'default': parsed['default'] ?? parsed['conf_threshold_default'] ?? 0.25,
        'low_confidence_threshold': parsed['low_confidence_threshold'],
        'pack_version': '${pack.crop}@${pack.version}',
      };
    } catch (_) {
      return {'default': 0.25, 'per_class': const {}};
    }
  }

  /// The lab scanners read `status.available`, not `model_available` - they
  /// were written against the server's CropRow shape, which differs from the
  /// potato one. Returning the wrong key here reads as "no model" with no
  /// error anywhere, so the shape is copied rather than unified.
  Future<Map<String, dynamic>> _detectorStatus(String name, String title) async {
    final pack = await PackStore.instance.packFor(name);
    if (pack == null) {
      return {
        'available': false,
        'version': null,
        'classes': const [],
        'conf_threshold': 0.25,
        'iou_threshold': 0.45,
        'note': '$title is not installed on this phone. Add it from '
            'Menu > Crop models.',
      };
    }
    final cfg = await _packJson(pack, 'thresholds.json');
    return {
      'available': true,
      'version': '${pack.crop}@${pack.version}',
      'classes': pack.manifest.classes,
      'conf_threshold': cfg['default'] ?? 0.25,
      'iou_threshold': cfg['iou_threshold'] ?? 0.45,
      'note': null,
    };
  }

  Future<Map<String, dynamic>> _detectorThresholds(String name) async {
    final pack = await PackStore.instance.packFor(name);
    if (pack == null) {
      return {'default': 0.25, 'per_class': const {}, 'classes': const []};
    }
    final cfg = await _packJson(pack, 'thresholds.json');
    return {
      'classes': cfg['classes'] ?? pack.manifest.classes,
      'per_class': cfg['per_class'] ?? const {},
      'default': cfg['default'] ?? 0.25,
      'iou_threshold': cfg['iou_threshold'] ?? 0.45,
      'pack_version': '${pack.crop}@${pack.version}',
    };
  }

  Future<Map<String, dynamic>> _packJson(InstalledPack pack, String rel) async {
    final raw = await PackStore.instance.readString(pack, rel);
    if (raw == null) return const {};
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return const {};
    }
  }

  Future<void> _serveDetectorModel(HttpRequest req, String name) async {
    final pack = await PackStore.instance.packFor(name);
    final bytes =
        pack == null ? null : await PackStore.instance.readFile(pack, 'model.onnx');
    if (bytes == null) {
      return _json(req, {
        'detail': 'The $name detector is not installed on this phone. Add it '
            'from Menu > Crop models.'
      }, status: 404);
    }
    req.response
      ..statusCode = 200
      ..headers.contentType = ContentType.binary
      ..headers.set('Cache-Control', 'public, max-age=86400')
      ..add(bytes);
    await req.response.close();
  }

  Future<void> _serveModel(HttpRequest req) async {
    final pack = await PackStore.instance.activePack();
    final bytes =
        pack == null ? null : await PackStore.instance.readFile(pack, 'model.onnx');
    if (bytes == null) {
      return _json(req, {
        'detail': 'No crop pack is installed, so there are no weights to '
            'serve. Install a crop from the catalogue first.'
      }, status: 404);
    }
    req.response
      ..statusCode = 200
      ..headers.contentType = ContentType.binary
      // Immutable for the life of this pack version, and the scanner refetches
      // it on every cold start otherwise.
      ..headers.set('Cache-Control', 'public, max-age=86400')
      ..add(bytes);
    await req.response.close();
  }

  /// `GET /api/dashboard/summary`, with every count genuinely zero.
  ///
  /// This device holds no case store yet, so zero is the true answer rather
  /// than a placeholder. Every key the server sends is present: the dashboard
  /// destructures `cases` and maps `by_class` without guarding, and a missing
  /// key there is a crash, not a blank panel.
  Map<String, dynamic> _dashboardSummary(int days, String? district) => {
        'window_days': days,
        'district': district,
        'cases': const {
          'total': 0,
          'from_image': 0,
          'proactive_risk_only': 0,
          'escalated': 0,
          'pending_review': 0,
          'expert_confirmed': 0,
          'escalation_rate': null,
        },
        'by_class': const [],
        // The server seeds all three levels, so the panel lists them at zero
        // instead of rendering nothing at all.
        'by_risk_level': const {'low': 0, 'medium': 0, 'high': 0},
        'high_risk_districts': const [],
        'follow_ups_overdue': 0,
        'active_sensor_devices': 0,
        'offline': true,
      };

  /// `GET /api/dashboard/trend` - one zeroed row per day in the window.
  ///
  /// The server emits `days + 1` rows covering the whole window whether or not
  /// cases exist, so the chart draws a flat line on a real date axis. An empty
  /// series would instead collapse the axis and look like a broken chart.
  Map<String, dynamic> _dashboardTrend(int days, String? classKey) {
    final since = DateTime.now().toUtc().subtract(Duration(days: days));
    final series = [
      for (var i = 0; i <= days; i++)
        {
          'date': _isoDate(since.add(Duration(days: i))),
          'total': 0,
          'confirmed': 0,
          'escalated': 0,
          'high_risk': 0,
        }
    ];
    return {
      'days': days,
      'class_key': classKey,
      'series': series,
      'offline': true,
    };
  }

  String _isoDate(DateTime d) => '${d.year.toString().padLeft(4, '0')}-'
      '${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';

  Future<Map<String, dynamic>> _body(HttpRequest req) async {
    if (req.method != 'POST') return {};
    try {
      final text = await utf8.decoder.bind(req).join();
      if (text.trim().isEmpty) return {};
      return jsonDecode(text) as Map<String, dynamic>;
    } catch (_) {
      return {};
    }
  }

  Map<String, dynamic> _health() => {
        'status': 'ok',
        'mode': 'offline',
        'degraded': [],
        'by_design': [
          {
            'code': 'offline_build',
            'detail': 'Running fully on-device. Weather uses the deterministic '
                'synthetic feed, and cross-farm outbreak data is unavailable '
                'until this device syncs.',
          },
          {
            'code': 'detector_not_bundled',
            'detail': 'No image detection model ships in this build; photo '
                'cases route to the expert queue.',
          },
        ],
      };

  // ------------------------------------------------------------------
  // Risk, computed on-device from the published models
  // ------------------------------------------------------------------
  Map<String, dynamic> _risk(double lat, double lon) {
    final series = getSeries(lat: lat, lon: lon);
    final days = summariseDays(series.points);

    final smith = smithPeriod(days);
    final beaumont = beaumontPeriod(series.points);
    final tomcast = tomcastDsv(days);
    final moth = degreeDays(days, kPestModels['potato_tuber_moth']!);
    final aphid = degreeDays(days, kPestModels['aphid_vector']!);

    final lateScore = [smith.score, beaumont.score].reduce((a, b) => a > b ? a : b);

    // Disease and pest scores are NOT comparable, and treating them as one
    // ranked list is a trap. Smith/Beaumont/TOMCAST answer "are infection
    // conditions present right now"; degree-days answer "how far through its
    // life cycle is this insect" - a phenology timer that saturates at 1.0
    // after any normal warm spell. Ranking them together let the aphid timer
    // own the traffic light permanently, so the farmer was told to go
    // photograph plants for aphids every single day.
    //
    // So: diseases drive the "walk your field today" decision; pest models are
    // reported alongside as emergence timing, which is what they actually are.
    final diseases = [
      _threat('potato_late_blight', lateScore, [smith, beaumont]),
      _threat('potato_early_blight', tomcast.score, [tomcast]),
    ]..sort((a, b) => (b['score'] as double).compareTo(a['score'] as double));

    final pests = [
      _threat('potato_tuber_moth', moth.score, [moth]),
      _threat('aphid_vector', aphid.score, [aphid]),
    ]..sort((a, b) => (b['score'] as double).compareTo(a['score'] as double));

    final top = diseases.first;
    return {
      'overall_level': top['level'],
      'overall_score': top['score'],
      'top_threat': top['key'],
      'top_threat_display': top['display'],
      'threats': [...diseases, ...pests],
      'disease_threats': diseases,
      'pest_threats': pests,
      'location': {
        'latitude': lat,
        'longitude': lon,
        'geo_cell': geoCell(lat, lon),
      },
      'weather': {
        'source': series.source,
        'synthetic': series.synthetic,
        'real_hours': series.realHours,
        'total_hours': series.points.length,
        'warnings': series.warnings,
      },
      'offline': true,
    };
  }

  Map<String, dynamic> _threat(
      String key, double score, List<ModelOutput> models) {
    return {
      'key': key,
      'display': displayName(key),
      'kind': classFor(key)?.kind ?? 'pest',
      'score': score,
      'level': score >= 0.75 ? 'high' : (score >= 0.4 ? 'medium' : 'low'),
      'models': models.map((m) => m.toJson()).toList(),
      'fired': models.where((m) => m.triggered).map((m) => m.name).toList(),
    };
  }

  /// The farmer's home traffic light.
  ///
  /// Weather half only. Cross-farm outbreak pressure needs other farmers'
  /// confirmed cases, which this device does not have offline, so the alert is
  /// driven purely by the agronomic models and says so.
  Map<String, dynamic> _overview(double lat, double lon) {
    final risk = _risk(lat, lon);
    final level = risk['overall_level'] as String;
    final status = level == 'high' ? 'act' : (level == 'medium' ? 'watch' : 'calm');
    final display = risk['top_threat_display'];

    // Only disease models justify "go and look at your plants today"; a pest
    // degree-day total is emergence timing, not a scouting trigger.
    final fired = <String>[];
    for (final t in risk['disease_threats'] as List) {
      fired.addAll(((t as Map)['fired'] as List).cast<String>());
    }

    final triage = evaluateTriage(
      modelAvailable: false,
      predictedClass: null,
      confidence: null,
      risk: {'top_threat': risk['top_threat'], 'overall_level': level},
    );

    return {
      'status': status,
      'action': const {'act': 'take_photo', 'watch': 'watch', 'calm': 'none'}[status],
      'time_hint': status == 'act'
          ? 'Photograph your plants this morning, while dew is still on the leaf.'
          : null,
      'primary_reason': status == 'act'
          ? 'The weather is right for $display to start.'
          : status == 'watch'
              ? 'Conditions are turning favourable for $display.'
              : 'No weather-driven disease pressure right now.',
      'include_demo': false,
      'data_thin': true,
      'offline': true,
      'location': risk['location'],
      'scouting': {
        'urgency': status,
        'should_scout': status != 'calm',
        'overall_level': level,
        'overall_score': risk['overall_score'],
        'focus_threat': risk['top_threat'],
        'focus_display': display,
        'fired_models': fired,
      },
      'propagation': {
        'level': 'unknown',
        'summary': 'Nearby outbreak data needs a connection. This alert is '
            'based on weather alone.',
        'confirmed_count': 0,
        'offline': true,
      },
      'triage': triage.toJson(),
      'weather': risk['weather'],
    };
  }
}
