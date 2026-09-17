/// Guards the shape of the offline `/api` surface against the web UI that
/// consumes it.
///
/// The dashboard and the review queue read their payloads positionally -
/// `summary.cases.total`, `rows.find(...)`, `summary.by_class.map(...)` - with
/// no guards. When the offline server answered those calls with an
/// `{items: [], offline: true}` envelope, the read threw during render, React
/// unmounted the whole tree, and the phone showed a blank white screen with no
/// navigation left. A 500 would have been friendlier.
///
/// So these tests assert the JSON *type and keys*, not the values. The values
/// are all legitimately zero on a device holding no cases; the shape is what
/// must not drift.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/local_server.dart';

void main() {
  late LocalServer server;
  late HttpClient client;
  late String origin;

  setUpAll(() async {
    server = LocalServer();
    origin = await server.start();
    client = HttpClient();
  });

  tearDownAll(() async {
    client.close(force: true);
    await server.stop();
  });

  Future<dynamic> get(String path) async {
    final req = await client.getUrl(Uri.parse('$origin/api$path'));
    final res = await req.close();
    expect(res.statusCode, 200, reason: 'GET /api$path');
    return jsonDecode(await utf8.decoder.bind(res).join());
  }

  group('officer dashboard', () {
    test('/dashboard/summary carries every key the page destructures',
        () async {
      final body = await get('/dashboard/summary?days=30&include_demo=false');
      expect(body, isA<Map>());

      // `const c = summary.cases` then `c.total`, `c.escalation_rate`, ...
      final cases = body['cases'];
      expect(cases, isA<Map>(), reason: 'summary.cases is read unguarded');
      for (final k in const [
        'total',
        'from_image',
        'proactive_risk_only',
        'escalated',
        'pending_review',
        'expert_confirmed',
        'escalation_rate',
      ]) {
        expect(cases, contains(k));
      }

      // `summary.by_class.map(...)` and `summary.high_risk_districts.length`
      expect(body['by_class'], isA<List>());
      expect(body['high_risk_districts'], isA<List>());

      // `Object.entries(summary.by_risk_level)` - a missing key here is a
      // throw, and an empty map renders an empty panel, so the server seeds
      // all three levels.
      expect(body['by_risk_level'], isA<Map>());
      expect(body['by_risk_level'], containsPair('low', 0));
      expect(body['by_risk_level'], containsPair('medium', 0));
      expect(body['by_risk_level'], containsPair('high', 0));

      // Rendered directly into stat tiles.
      expect(body['follow_ups_overdue'], isA<int>());
      expect(body['active_sensor_devices'], isA<int>());
    });

    test('/dashboard/trend returns one row per day, not an empty series',
        () async {
      final body = await get('/dashboard/trend?days=7&include_demo=false');
      final series = body['series'] as List;
      // days + 1, matching the Python router, so the chart has a real axis.
      expect(series.length, 8);
      for (final row in series) {
        expect(row, isA<Map>());
        expect(row['date'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}$')));
        for (final k in const ['total', 'confirmed', 'escalated', 'high_risk']) {
          expect(row[k], isA<int>());
        }
      }
    });

    test('/dashboard/districts returns a districts list, not an envelope',
        () async {
      // The page does `.then((d) => setDistricts(d.districts))` with an empty
      // catch, so a missing key lands in state and blows up on the next render.
      final body = await get('/dashboard/districts?include_demo=false');
      expect(body['districts'], isA<List>());
    });

    test('/review/stats/accuracy and /followups/stats keep their stat keys',
        () async {
      final acc = await get('/review/stats/accuracy?include_demo=false');
      expect(acc['per_class'], isA<List>());
      expect(acc, contains('field_accuracy'));
      expect(acc, contains('reviewed'));
      expect(acc, contains('corrected'));

      final fu = await get('/followups/stats?include_demo=false');
      expect(fu, contains('improvement_rate'));
      expect(fu['counts'], isA<Map>());
    });
  });

  group('expert review', () {
    test('/review/queue is a JSON array', () async {
      // `rows.find(...)` and `queue.map(...)`. An object here set queue to a
      // non-array and crashed the render.
      final body = await get('/review/queue?limit=60&include_demo=false');
      expect(body, isA<List>());
      expect(body, isEmpty);
    });

    test('other list endpoints are arrays too', () async {
      for (final path in const [
        '/followups?include_demo=false',
        '/sensors?include_demo=false',
        '/dashboard/cases',
      ]) {
        expect(await get(path), isA<List>(), reason: path);
      }
    });
  });

  group('hotspot map', () {
    test('/hotspots carries the caption fields the map prints', () async {
      // `data ? data.total_confirmed : 0` - truthy object, missing key, so the
      // page rendered the string "undefined confirmed - undefined pending".
      final body = await get('/hotspots?days=30&cell_size_deg=0.02&include_demo=false');
      expect(body['total_confirmed'], isA<int>());
      expect(body['total_unverified'], isA<int>());
      expect(body['unverified_weight'], 0.4);
      expect(body['cells'], isA<List>());
      // Echoed back, not defaulted, or the caption contradicts the grid.
      expect(body['cell_size_deg'], 0.02);
    });

    test('/hotspots/points pins the heat ramp scale', () async {
      final body = await get('/hotspots/points?days=30&include_demo=false');
      expect(body['points'], isA<List>());
      // `points?.severe_threshold || 8` - the client default happens to match,
      // but relying on that would re-scale the map the moment sync fills it.
      expect(body['severe_threshold'], 8.0);
      expect(body['total_points'], 0);
    });
  });

  group('demo data', () {
    // include_demo is the UI's "Demo + live" toggle and defaults to on, so
    // these paths are what a farmer actually sees. The dataset itself is not
    // loadable in a plain unit test (no asset bundle), so what is asserted
    // here is the contract that holds either way: the shape stays the server's,
    // and nothing is ever silently passed off as a real field report.
    test('the default is include_demo=true and it still returns the right types',
        () async {
      expect(await get('/review/queue?limit=60'), isA<List>());
      final summary = await get('/dashboard/summary?days=30');
      expect(summary['cases'], isA<Map>());
      expect(summary['by_class'], isA<List>());
      expect(summary['by_risk_level'], isA<Map>());
    });

    test('live-only is explicitly empty rather than absent', () async {
      final summary = await get('/dashboard/summary?days=30&include_demo=false');
      expect(summary['offline'], isTrue);
      expect((summary['cases'] as Map)['total'], 0);
      expect(await get('/review/queue?include_demo=false'), isEmpty);
    });
  });

  group('crop packs', () {
    test('/packs/installed reports an empty install, not an error', () async {
      // No pack in a unit-test environment; the endpoint must still answer in
      // the shape a picker can render.
      final body = await get('/packs/installed');
      expect(body['installed'], isA<List>());
      expect(body, contains('active'));
    });

    test('detection reports itself unavailable when no pack is installed',
        () async {
      final body = await get('/detect/status');
      expect(body['model_available'], isFalse);
      // The honest-absence rule: no pack means the case goes to a human, not
      // to a guess.
      expect(body['note'], contains('expert queue'));
    });

    test('/detect/model 404s rather than serving an empty body', () async {
      // An empty 200 would hand onnxruntime a zero-byte buffer and surface as
      // an opaque wasm error in the page instead of a missing pack.
      final req = await client.getUrl(Uri.parse('$origin/api/detect/model'));
      final res = await req.close();
      expect(res.statusCode, 404);
      await res.drain<void>();
    });

    test('/packs/progress answers before any install has run', () async {
      // The models page polls this on mount; an idle server must answer in the
      // same shape as a running one, or the page reads `undefined.active`.
      final body = await get('/packs/progress');
      expect(body['active'], isFalse);
      expect(body['phase'], 'idle');
      expect(body['received_bytes'], 0);
      expect(body['total_bytes'], 0);
    });

    test('/packs/install returns immediately rather than holding the request',
        () async {
      // A 45 MB download must not block the HTTP response: the page would have
      // to choose between a dead spinner and a timeout. 202 plus polling.
      final req = await client.postUrl(Uri.parse('$origin/api/packs/install'));
      req.headers.contentType = ContentType.json;
      req.write('{"crop":"potato"}');
      final res = await req.close();
      expect(res.statusCode, 202);
      final body = jsonDecode(await utf8.decoder.bind(res).join());
      expect(body['started'], isTrue);
      expect(body['crop'], 'potato');
    });

    test('/packs/install rejects a request with no crop', () async {
      final req = await client.postUrl(Uri.parse('$origin/api/packs/install'));
      req.headers.contentType = ContentType.json;
      req.write('{}');
      final res = await req.close();
      expect(res.statusCode, 400);
      await res.drain<void>();
    });

    test('advisory declines rather than composing an empty treatment plan',
        () async {
      final req = await client.postUrl(Uri.parse('$origin/api/advisory'));
      req.headers.contentType = ContentType.json;
      req.write('{"class_key":"potato_late_blight","language":"en"}');
      final res = await req.close();
      expect(res.statusCode, 200);
      final body = jsonDecode(await utf8.decoder.bind(res).join());
      // Triage still runs with no pack - the safety gate does not depend on
      // having weights - but there is no advisory body to give.
      expect(body['advisory'], isNull);
      expect(body['triage'], isA<Map>());
      expect(body['detail'], contains('No crop pack'));
    });
  });

  group('static assets', () {
    test('a missing asset 404s instead of being answered with index.html',
        () async {
      // The SPA fallback used to answer everything with index.html. A missing
      // ONNX runtime module therefore came back as 200 text/html, and the
      // browser reported a MIME type error - which reads as a server
      // misconfiguration rather than a file that was never shipped.
      final req = await client
          .getUrl(Uri.parse('$origin/ort/ort-wasm-simd-threaded.jsep.mjs'));
      final res = await req.close();
      expect(res.statusCode, 404);
      await res.drain<void>();
    });

    test('the ONNX runtime the scanner needs is actually staged', () {
      // Asserted against the staged directory rather than over HTTP, because a
      // plain unit test has no asset bundle to serve from. The staged files are
      // where the risk lives anyway: stage_web.ps1 deletes runtimes it believes
      // are unused, and deleting one ORT actually loads is exactly the bug this
      // guards. The symptom was every on-device session failing with "no
      // available backend found".
      final dir = Directory('assets/web/ort');
      expect(dir.existsSync(), isTrue,
          reason: 'run mobileapp/tools/stage_web.ps1');
      for (final f in const [
        'ort-wasm-simd-threaded.mjs',
        'ort-wasm-simd-threaded.wasm',
      ]) {
        final file = File('${dir.path}/$f');
        expect(file.existsSync(), isTrue, reason: 'missing staged $f');
        expect(file.lengthSync(), greaterThan(1000), reason: '$f is a stub');
      }
    });

    test('the bundled UI asks for the wasm-only runtime, not the jsep one', () {
      // `onnxruntime-web` (the default entry) dynamically imports
      // ort-wasm-simd-threaded.jsep.mjs even when you request the wasm provider
      // with one thread. We do not ship that 26.5 MB binary, so the import
      // 404'd. Importing `onnxruntime-web/wasm` is what keeps the staged pair
      // sufficient - and this asserts the built bundle really does that.
      final js = Directory('assets/web/assets')
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.js'))
          .toList();
      expect(js, isNotEmpty, reason: 'run mobileapp/tools/stage_web.ps1');
      final source = js.map((f) => f.readAsStringSync()).join();
      expect(source.contains('ort-wasm-simd-threaded.mjs'), isTrue,
          reason: 'the plain wasm runtime is never requested');
      expect(source.contains('jsep.mjs'), isFalse,
          reason: 'the bundle still reaches for the jsep runtime we do not ship');
    });
  });

  group('honest failure', () {
    test('an endpoint with no offline answer says so with a 503', () async {
      // Better than a wrong-shaped 200: the api client turns `detail` into a
      // thrown Error, which the pages render as a readable banner.
      final req = await client.getUrl(Uri.parse('$origin/api/advisory/nope'));
      final res = await req.close();
      expect(res.statusCode, 503);
      final body = jsonDecode(await utf8.decoder.bind(res).join());
      expect(body['detail'], contains('network connection'));
    });
  });
}
