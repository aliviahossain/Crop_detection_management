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

import 'domain/geo.dart';
import 'domain/risk_models.dart';
import 'domain/taxonomy.dart';
import 'domain/triage.dart';
import 'domain/weather.dart';

const String _assetRoot = 'assets/web';

class LocalServer {
  HttpServer? _server;

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
      // Unknown path: hand back index.html so client-side routing works on a
      // deep link or a refresh.
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

      // No detector is bundled in this build. Report that honestly rather than
      // returning a guessed class - the same rule the server follows.
      case '/detect/status':
      case '/croprow/status':
      case '/crophealth/status':
        return _json(req, {
          'model_available': false,
          'model_version': null,
          'classes': kClassNames,
          'note': 'No detector is bundled in this offline build. Photographs '
              'are routed to the expert queue instead of being guessed at.',
        });

      case '/detect/thresholds':
      case '/croprow/thresholds':
      case '/crophealth/thresholds':
        return _json(req, {'default': 0.25, 'per_class': {}});

      case '/chat/status':
        return _json(req, {
          'mode': 'offline',
          'note': 'The assistant needs a network connection. Advisories, risk '
              'forecasts and diagnosis guidance all work offline.',
        });

      // Cross-farm intelligence needs other farmers' cases, so it is empty
      // offline rather than fabricated.
      case '/hotspots':
        return _json(req, {'cells': [], 'offline': true});
      case '/hotspots/points':
        return _json(req, {'points': [], 'offline': true});
      case '/review/queue':
        return _json(req, {'items': [], 'total': 0, 'offline': true});
      case '/followups':
        return _json(req, {'items': [], 'total': 0, 'offline': true});
      case '/sensors':
        return _json(req, {'items': [], 'total': 0, 'offline': true});
      case '/dashboard/summary':
        return _json(req, {'offline': true, 'total_cases': 0});
    }

    if (path.startsWith('/dashboard/') ||
        path.startsWith('/review/') ||
        path.startsWith('/sensors/') ||
        path.startsWith('/followups/')) {
      return _json(req, {'items': [], 'total': 0, 'offline': true});
    }

    return _json(req, {
      'detail': 'This feature needs a network connection and is not available '
          'in the offline build.'
    }, status: 503);
  }

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
    final threats = [
      _threat('potato_late_blight', lateScore, [smith, beaumont]),
      _threat('potato_early_blight', tomcast.score, [tomcast]),
      _threat('potato_tuber_moth', moth.score, [moth]),
      _threat('aphid_vector', aphid.score, [aphid]),
    ]..sort((a, b) =>
        (b['score'] as double).compareTo(a['score'] as double));

    final top = threats.first;
    return {
      'overall_level': top['level'],
      'overall_score': top['score'],
      'top_threat': top['key'],
      'top_threat_display': top['display'],
      'threats': threats,
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

    final fired = <String>[];
    for (final t in risk['threats'] as List) {
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
