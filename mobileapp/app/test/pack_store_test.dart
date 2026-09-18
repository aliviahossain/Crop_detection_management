/// Proves the pack installer refuses what it cannot verify.
///
/// This is the security-relevant path in the whole app. A crop pack carries
/// pesticide dose tables and the thresholds that decide whether a detection is
/// reported at all, so "downloaded successfully" is not the bar - "downloaded,
/// and byte-for-byte what the manifest says" is. TLS protects the transport,
/// not a compromised bucket, a truncated response or a wrong upload.
///
/// Runs against a real HTTP server on loopback rather than a mocked client, so
/// the bytes genuinely travel and a partial write genuinely happens.
library;

import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/packs/pack.dart';
import 'package:cropguard/packs/pack_store.dart';

/// Serves an in-memory pack, with hooks to corrupt exactly one file.
class _FakeOrigin {
  _FakeOrigin(this.files);

  final Map<String, List<int>> files;

  /// Path whose body is served corrupted, to exercise the checksum gate.
  String? corrupt;

  /// Path whose body is served truncated, to exercise the length gate.
  String? truncate;

  HttpServer? _server;
  String get base => 'http://127.0.0.1:${_server!.port}';

  Future<void> start() async {
    _server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server!.listen((req) async {
      final path = req.uri.path.substring(1);
      var body = files[path];
      if (body == null) {
        req.response.statusCode = 404;
        await req.response.close();
        return;
      }
      if (path == corrupt) {
        body = [...body];
        body[0] = body[0] ^ 0xFF;
      }
      if (path == truncate) {
        body = body.sublist(0, body.length ~/ 2);
      }
      req.response
        ..statusCode = 200
        ..add(body);
      await req.response.close();
    });
  }

  Future<void> stop() async => _server?.close(force: true);
}

/// Builds a pack the way `build_pack.py` does: payload first, then a manifest
/// whose hashes are computed from those exact bytes.
({Map<String, List<int>> files, Map<String, dynamic> index}) _buildPack({
  String crop = 'potato',
  String version = '1.0.0',
  String minAppVersion = '1.0.0',
  String kind = 'crop',
}) {
  final payload = <String, List<int>>{
    'model.onnx': utf8.encode('not really onnx, but the bytes are the bytes'),
    'thresholds.json': utf8.encode('{"default":0.25,"per_class":{}}'),
    'taxonomy.json': utf8.encode('{"crop":"$crop","classes":[]}'),
    'strings.json': utf8.encode('{"classes":{},"advisory":{}}'),
    'kb/potato_late_blight.md':
        utf8.encode('---\nid: potato_late_blight\n---\n# Late blight\n'),
  };

  final manifest = <String, dynamic>{
    'pack_format': 1,
    'kind': kind,
    'crop': crop,
    'version': version,
    'built_at': '2026-09-17T00:00:00+00:00',
    'min_app_version': minAppVersion,
    'classes': ['potato_late_blight'],
    'files': [
      for (final e in payload.entries)
        {
          'path': e.key,
          'bytes': e.value.length,
          'sha256': sha256.convert(e.value).toString(),
        }
    ],
    'signature': null,
  };
  manifest['total_bytes'] = payload.values.fold<int>(0, (s, b) => s + b.length);

  final prefix = '$crop/$version';
  final files = <String, List<int>>{
    'packs/$prefix/manifest.json': utf8.encode(jsonEncode(manifest)),
    for (final e in payload.entries) 'packs/$prefix/${e.key}': e.value,
  };

  final index = {
    'pack_format': 1,
    'crops': [
      {
        'crop': crop,
        'kind': kind,
        'latest': version,
        'versions': [
          {
            'version': version,
            'built_at': manifest['built_at'],
            'total_bytes': manifest['total_bytes'],
            'min_app_version': minAppVersion,
            'classes': manifest['classes'],
            'manifest': '$prefix/manifest.json',
          }
        ],
      }
    ],
  };
  files['packs/index.json'] = utf8.encode(jsonEncode(index));
  return (files: files, index: index);
}

void main() {
  late Directory tmp;
  late _FakeOrigin origin;
  late PackStore store;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('cropguard_packs_test');
    final built = _buildPack();
    origin = _FakeOrigin(built.files);
    await origin.start();
    store = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
  });

  tearDown(() async {
    await origin.stop();
    if (await tmp.exists()) await tmp.delete(recursive: true);
  });

  Future<CatalogVersion> firstVersion() async {
    final crops = await store.catalog();
    return crops.single.latestVersion!;
  }

  test('reads the catalogue', () async {
    final crops = await store.catalog();
    expect(crops, hasLength(1));
    expect(crops.single.crop, 'potato');
    expect(crops.single.latest, '1.0.0');
  });

  test('installs a good pack and serves its files back', () async {
    final crops = await store.catalog();
    final pack = await store.install(crops.single, await firstVersion());

    expect(pack.crop, 'potato');
    expect(pack.version, '1.0.0');
    expect(await store.readString(pack, 'thresholds.json'),
        '{"default":0.25,"per_class":{}}');
    expect(await store.readString(pack, 'kb/potato_late_blight.md'),
        contains('Late blight'));
    // Reading back through a fresh store proves it is on disk, not in memory.
    final reopened = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    expect((await reopened.packFor('potato'))?.version, '1.0.0');
  });

  test('refuses a pack whose file fails its checksum, and installs nothing',
      () async {
    origin.corrupt = 'packs/potato/1.0.0/thresholds.json';
    final crops = await store.catalog();

    await expectLater(
      store.install(crops.single, await firstVersion()),
      throwsA(isA<PackException>()),
    );

    // The real assertion: not one byte of a failed install is visible. A pack
    // half-written by a dropped connection is a model with no thresholds,
    // which reads as a confident wrong answer rather than a missing one.
    expect(await store.packFor('potato'), isNull);
    final cropDir = Directory('${tmp.path}/packs/potato');
    expect(cropDir.existsSync(), isFalse);
  });

  test('refuses a truncated download even before hashing', () async {
    origin.truncate = 'packs/potato/1.0.0/model.onnx';
    final crops = await store.catalog();
    await expectLater(
      store.install(crops.single, await firstVersion()),
      throwsA(isA<PackException>()),
    );
    expect(await store.packFor('potato'), isNull);
  });

  test('leaves no staging directory behind after a failure', () async {
    origin.corrupt = 'packs/potato/1.0.0/model.onnx';
    final crops = await store.catalog();
    await expectLater(
      store.install(crops.single, await firstVersion()),
      throwsA(isA<PackException>()),
    );
    final staging = Directory('${tmp.path}/packs/.staging');
    // Either gone, or empty - what must not happen is a stale half-pack
    // accumulating on a phone with 2 GB free.
    expect(
      !staging.existsSync() || staging.listSync().isEmpty,
      isTrue,
      reason: 'staging left behind: ${staging.existsSync() ? staging.listSync() : ''}',
    );
  });

  test('refuses a pack that needs a newer app than this build', () async {
    final built = _buildPack(version: '2.0.0', minAppVersion: '9.9.9');
    await origin.stop();
    origin = _FakeOrigin(built.files);
    await origin.start();
    store = PackStore(catalogBase: '${origin.base}/packs', root: tmp);

    final crops = await store.catalog();
    await expectLater(
      store.install(crops.single, crops.single.latestVersion!),
      throwsA(predicate(
          (e) => e is PackException && e.message.contains('or newer'))),
    );
  });

  test('refuses a manifest describing a different pack than advertised',
      () async {
    // A catalogue that points at the wrong manifest is either a bad deploy or
    // a substitution attack. Both end the same way.
    final built = _buildPack(crop: 'potato', version: '1.0.0');
    final files = {...built.files};
    final swapped = jsonDecode(utf8.decode(files['packs/potato/1.0.0/manifest.json']!))
        as Map<String, dynamic>;
    swapped['crop'] = 'tomato';
    files['packs/potato/1.0.0/manifest.json'] = utf8.encode(jsonEncode(swapped));

    await origin.stop();
    origin = _FakeOrigin(files);
    await origin.start();
    store = PackStore(catalogBase: '${origin.base}/packs', root: tmp);

    final crops = await store.catalog();
    await expectLater(
      store.install(crops.single, crops.single.latestVersion!),
      throwsA(predicate(
          (e) => e is PackException && e.message.contains('Refusing to install'))),
    );
  });

  test('reports progress that ends at the full payload size', () async {
    final crops = await store.catalog();
    final version = await firstVersion();
    final seen = <PackProgress>[];
    await store.install(crops.single, version, onProgress: seen.add);

    expect(seen, isNotEmpty);
    expect(seen.last.phase, 'done');
    expect(seen.last.receivedBytes, version.totalBytes);
    expect(seen.last.fraction, 1.0);
    // Monotonic: a bar that jumps backwards reads as a stall.
    for (var i = 1; i < seen.length; i++) {
      expect(seen[i].receivedBytes, greaterThanOrEqualTo(seen[i - 1].receivedBytes));
    }
  });

  test('a newer version replaces the old one and becomes active', () async {
    final crops = await store.catalog();
    await store.install(crops.single, await firstVersion());

    final v2 = _buildPack(version: '1.10.0');
    await origin.stop();
    origin = _FakeOrigin(v2.files);
    await origin.start();
    final store2 = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    final crops2 = await store2.catalog();
    await store2.install(crops2.single, crops2.single.latestVersion!);

    // 1.10.0 beats 1.0.0 numerically; a string compare would pick 1.0.0 and
    // quietly serve the older weights forever.
    final active = await store2.activePack();
    expect(active?.version, '1.10.0');
  });

  test('installing an older version rolls back rather than keeping the newer',
      () async {
    // Withdrawing a bad pack has to actually withdraw it. `_scan` resolves a
    // crop to its highest version, so without pruning the old directory the
    // operator sees "installed 1.0.0" while the farmer keeps scanning with the
    // 1.0.1 weights that were being pulled.
    final crops = await store.catalog();
    await store.install(crops.single, await firstVersion()); // 1.0.0

    final v2 = _buildPack(version: '1.0.1');
    await origin.stop();
    origin = _FakeOrigin(v2.files);
    await origin.start();
    var s2 = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    await s2.install((await s2.catalog()).single, (await s2.catalog()).single.latestVersion!);
    expect((await s2.activePack())?.version, '1.0.1');

    // Now roll back.
    final v1 = _buildPack(version: '1.0.0');
    await origin.stop();
    origin = _FakeOrigin(v1.files);
    await origin.start();
    s2 = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    final back = await s2.install(
        (await s2.catalog()).single, (await s2.catalog()).single.latestVersion!);

    expect(back.version, '1.0.0');
    expect((await s2.activePack())?.version, '1.0.0');
    // And the superseded copy is gone: these are ~45 MB each in production.
    final versions = Directory('${tmp.path}/packs/potato')
        .listSync()
        .whereType<Directory>()
        .map((d) => d.path.split(Platform.pathSeparator).last)
        .toList();
    expect(versions, ['1.0.0']);
  });

  test('a detector pack never becomes the active crop', () async {
    // Installing Crop row scan used to repoint /detect at a lettuce localiser,
    // because "most recently installed" was the whole rule. The potato scanner
    // would then return boxes labelled "lettuce", with no error anywhere.
    final crops = await store.catalog();
    await store.install(crops.single, await firstVersion()); // potato, a crop
    expect((await store.activePack())?.crop, 'potato');

    final det = _buildPack(crop: 'croprow', version: '1.0.0', kind: 'detector');
    await origin.stop();
    origin = _FakeOrigin(det.files);
    await origin.start();
    final s2 = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    await s2.install((await s2.catalog()).single, (await s2.catalog()).single.latestVersion!);

    // Installed and readable...
    expect((await s2.packFor('croprow'))?.version, '1.0.0');
    // ...but the farmer's scanner still points at the crop.
    expect((await s2.activePack())?.crop, 'potato');
  });

  test('a detector alone leaves the crop scanner with nothing, not a lettuce',
      () async {
    final det = _buildPack(crop: 'croprow', version: '1.0.0', kind: 'detector');
    await origin.stop();
    origin = _FakeOrigin(det.files);
    await origin.start();
    final s2 = PackStore(catalogBase: '${origin.base}/packs', root: tmp);
    await s2.install((await s2.catalog()).single, (await s2.catalog()).single.latestVersion!);

    expect(await s2.packFor('croprow'), isNotNull);
    // No crop pack installed, so there is no active crop. Reporting the
    // detector here would be worse than reporting nothing.
    expect(await s2.activePack(), isNull);
  });

  test('compareVersions orders numerically, not lexically', () {
    expect(compareVersions('1.10.0', '1.9.0'), greaterThan(0));
    expect(compareVersions('1.0.0', '1.0.0'), 0);
    expect(compareVersions('2.0', '1.9.9'), greaterThan(0));
  });
}
