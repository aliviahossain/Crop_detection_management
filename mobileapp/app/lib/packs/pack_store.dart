/// Downloads, verifies and installs crop packs, and reads the installed ones.
///
/// Three rules this file exists to enforce:
///
///   * **Verify before install.** Every file is checked against the SHA-256 in
///     the manifest. The payload contains pesticide dose tables; TLS protects
///     the transport, not a compromised bucket or a wrong upload.
///   * **Install atomically.** Download to a staging directory, verify the
///     whole set, then move it into place. A pack half-written by a dropped
///     connection is a model with no thresholds, which reads as a confident
///     wrong answer rather than a missing one.
///   * **Documents, never cache.** Android evicts the cache directory under
///     storage pressure. A pack that vanishes mid-season would break offline
///     use precisely when the farmer cannot re-download it.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'pack.dart';

/// Where the catalogue lives, as compiled in.
///
/// This is only the default. The effective URL is whatever is stored in
/// `<documents>/packs/catalog_url`, which the app can set at runtime — because
/// a build-time-only constant means a handset pointed at a dead host can never
/// be recovered without reinstalling, which is not a thing you can ask a
/// farmer to do.
const String kPackCatalogBase = String.fromEnvironment(
  'PACK_CATALOG_BASE',
  defaultValue: 'https://packs.cropguard.in/packs',
);

/// This app build. A pack declaring a higher `min_app_version` is listed but
/// refused, rather than installed and then misread.
const String kAppVersion = '1.0.0';

class PackException implements Exception {
  PackException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Progress of an in-flight install, for the UI.
class PackProgress {
  const PackProgress({
    required this.receivedBytes,
    required this.totalBytes,
    required this.file,
    required this.phase,
  });

  final int receivedBytes;
  final int totalBytes;
  final String file;

  /// `catalog` | `manifest` | `download` | `verify` | `install` | `done`
  final String phase;

  double get fraction =>
      totalBytes <= 0 ? 0 : (receivedBytes / totalBytes).clamp(0.0, 1.0);
}

class PackStore {
  PackStore({http.Client? client, String? catalogBase, Directory? root})
      : _client = client ?? http.Client(),
        _catalogBase = (catalogBase ?? kPackCatalogBase).replaceAll(
          RegExp(r'/+$'),
          '',
        ),
        _rootOverride = root;

  static final PackStore instance = PackStore();

  final http.Client _client;
  final String _catalogBase;
  final Directory? _rootOverride;

  /// Runtime override, read from disk once and cached.
  String? _catalogOverride;
  bool _catalogOverrideLoaded = false;

  Directory? _root;
  final Map<String, InstalledPack> _installed = {};
  bool _scanned = false;

  /// `<app documents>/packs`
  ///
  /// Throws if the documents directory cannot be resolved, which is a real
  /// failure for an install. Read paths use [_packsRootOrNull] instead: not
  /// being able to find storage means "no packs", not "crash every officer
  /// screen".
  Future<Directory> _packsRoot() async {
    if (_root != null) return _root!;
    final base = _rootOverride ?? await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(base.path, 'packs'));
    await dir.create(recursive: true);
    _root = dir;
    return dir;
  }

  Future<Directory?> _packsRootOrNull() async {
    try {
      return await _packsRoot();
    } catch (_) {
      // No plugin (unit tests), or no writable storage. Either way there is
      // nothing installed, and saying so is more useful than a 500.
      return null;
    }
  }

  // ------------------------------------------------------------------
  // Installed packs
  // ------------------------------------------------------------------

  /// Every verified pack on disk, newest version per crop.
  Future<List<InstalledPack>> installed() async {
    await _scan();
    return _installed.values.toList()
      ..sort((a, b) => a.crop.compareTo(b.crop));
  }

  Future<InstalledPack?> packFor(String crop) async {
    await _scan();
    return _installed[crop];
  }

  /// The crop pack the farmer's diagnosis path serves from.
  ///
  /// Crop packs only. A lab detector is not a crop and must never become the
  /// active one: installing Crop row scan would otherwise repoint /detect at a
  /// lettuce localiser, and the potato scanner would start returning boxes
  /// labelled "lettuce" with no error anywhere.
  Future<InstalledPack?> activePack() async {
    await _scan();
    final crops = {
      for (final e in _installed.entries)
        if (e.value.manifest.isCrop) e.key: e.value
    };
    if (crops.isEmpty) return null;
    final root = await _packsRootOrNull();
    if (root == null) return crops.values.first;
    final marker = File(p.join(root.path, 'active'));
    if (await marker.exists()) {
      final crop = (await marker.readAsString()).trim();
      final hit = crops[crop];
      if (hit != null) return hit;
    }
    return crops.values.first;
  }

  Future<void> setActive(String crop) async {
    final root = await _packsRootOrNull();
    if (root == null) return;
    await File(p.join(root.path, 'active')).writeAsString(crop);
  }

  Future<void> _scan({bool force = false}) async {
    if (_scanned && !force) return;
    _installed.clear();
    final root = await _packsRootOrNull();
    _scanned = true;
    if (root == null) return;
    if (await root.exists()) {
      for (final cropDir in root.listSync().whereType<Directory>()) {
        final crop = p.basename(cropDir.path);
        if (crop.startsWith('.')) continue; // staging
        InstalledPack? best;
        for (final vdir in cropDir.listSync().whereType<Directory>()) {
          final mf = File(p.join(vdir.path, 'manifest.json'));
          if (!mf.existsSync()) continue;
          try {
            final m = PackManifest.fromJson(
              jsonDecode(mf.readAsStringSync()) as Map<String, dynamic>,
            );
            if (best == null ||
                compareVersions(m.version, best.manifest.version) > 0) {
              best = InstalledPack(manifest: m, dir: vdir.path);
            }
          } catch (_) {
            // A manifest we cannot parse is not a pack. Leave it on disk for
            // forensics rather than serving half of it.
          }
        }
        if (best != null) _installed[crop] = best;
      }
    }
  }

  /// Reads one file out of an installed pack. Returns null when absent, so a
  /// pack built without an optional page degrades instead of throwing.
  Future<List<int>?> readFile(InstalledPack pack, String relPath) async {
    final f = File(p.join(pack.dir, relPath.replaceAll('/', p.separator)));
    if (!await f.exists()) return null;
    return f.readAsBytes();
  }

  Future<String?> readString(InstalledPack pack, String relPath) async {
    final bytes = await readFile(pack, relPath);
    return bytes == null ? null : utf8.decode(bytes);
  }

  // ------------------------------------------------------------------
  // Catalogue
  // ------------------------------------------------------------------

  File? _catalogUrlFile(Directory root) =>
      File(p.join(root.path, 'catalog_url'));

  /// The URL actually used: the runtime override if one was set, else the
  /// compiled-in default.
  Future<String> catalogBase() async {
    if (_rootOverride != null) return _catalogBase; // tests pin it explicitly
    if (!_catalogOverrideLoaded) {
      _catalogOverrideLoaded = true;
      final root = await _packsRootOrNull();
      if (root != null) {
        final f = _catalogUrlFile(root)!;
        if (await f.exists()) {
          final v = (await f.readAsString()).trim();
          if (v.isNotEmpty) _catalogOverride = v;
        }
      }
    }
    return (_catalogOverride ?? _catalogBase).replaceAll(RegExp(r'/+$'), '');
  }

  /// Points this device at a different catalogue. Persisted, so it survives a
  /// restart; an app update does not clear it, because it lives in documents.
  Future<void> setCatalogBase(String? url) async {
    final root = await _packsRootOrNull();
    if (root == null) return;
    final f = _catalogUrlFile(root)!;
    final clean = url?.trim();
    if (clean == null || clean.isEmpty) {
      if (await f.exists()) await f.delete();
      _catalogOverride = null;
    } else {
      await f.writeAsString(clean);
      _catalogOverride = clean;
    }
    _catalogOverrideLoaded = true;
  }

  /// The crops on offer. This is the one call that needs a connection.
  Future<List<CatalogCrop>> catalog() async {
    final base = await catalogBase();
    final uri = Uri.parse('$base/index.json');
    late http.Response res;
    try {
      res = await _client.get(uri).timeout(const Duration(seconds: 20));
    } on Object catch (e) {
      throw PackException('Could not reach the crop catalogue: $e');
    }
    if (res.statusCode != 200) {
      throw PackException(
        'Crop catalogue returned ${res.statusCode} from $uri.',
      );
    }
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    return ((body['crops'] as List?) ?? const [])
        .map((c) => CatalogCrop.fromJson((c as Map).cast<String, dynamic>()))
        .toList();
  }

  // ------------------------------------------------------------------
  // Install
  // ------------------------------------------------------------------

  /// Download, verify and install one pack version.
  ///
  /// `onProgress` reports bytes across the whole payload, so the UI can show
  /// one bar rather than a per-file flicker.
  Future<InstalledPack> install(
    CatalogCrop crop,
    CatalogVersion version, {
    void Function(PackProgress)? onProgress,
    bool allowUnsigned = true,
  }) async {
    void report(String phase, int got, int total, String file) =>
        onProgress?.call(PackProgress(
          receivedBytes: got,
          totalBytes: total,
          file: file,
          phase: phase,
        ));

    report('manifest', 0, version.totalBytes, 'manifest.json');
    final manifest = await _fetchManifest(version.manifestPath);

    if (manifest.crop != crop.crop || manifest.version != version.version) {
      throw PackException(
        'Catalogue offered ${crop.crop}@${version.version} but the manifest '
        'describes ${manifest.crop}@${manifest.version}. Refusing to install.',
      );
    }
    if (compareVersions(manifest.minAppVersion, kAppVersion) > 0) {
      throw PackException(
        '${manifest.crop} ${manifest.version} needs CropGuard '
        '${manifest.minAppVersion} or newer. Update the app first.',
      );
    }
    if (manifest.signature == null && !allowUnsigned) {
      throw PackException(
        'Pack ${manifest.crop}@${manifest.version} is unsigned.',
      );
    }

    final root = await _packsRoot();
    // Staging lives under the same root so the final move is a rename within
    // one filesystem, which is what makes it atomic.
    final staging = Directory(
      p.join(root.path, '.staging', '${manifest.crop}-${manifest.version}'),
    );
    if (await staging.exists()) await staging.delete(recursive: true);
    await staging.create(recursive: true);

    try {
      final total = manifest.totalBytes;
      var got = 0;
      final catalogRoot = await catalogBase();
      final base = p.url.dirname(version.manifestPath);
      for (final entry in manifest.files) {
        report('download', got, total, entry.path);
        final url = Uri.parse('$catalogRoot/$base/${entry.path}');
        final bytes = await _download(url);
        if (bytes.length != entry.bytes) {
          throw PackException(
            '${entry.path}: expected ${entry.bytes} bytes, got ${bytes.length}.',
          );
        }
        report('verify', got, total, entry.path);
        final digest = sha256.convert(bytes).toString();
        if (digest != entry.sha256) {
          // Do not keep it, do not install it, do not tell the user it worked.
          throw PackException(
            '${entry.path} failed its checksum. The download was corrupted or '
            'the file on the server is not the one this manifest describes.',
          );
        }
        final dest = File(
          p.join(staging.path, entry.path.replaceAll('/', p.separator)),
        );
        await dest.parent.create(recursive: true);
        await dest.writeAsBytes(bytes, flush: true);
        got += bytes.length;
        report('download', got, total, entry.path);
      }

      await File(p.join(staging.path, 'manifest.json')).writeAsString(
        jsonEncode(manifest.toJson()),
        flush: true,
      );

      report('install', total, total, '');
      final finalDir = Directory(
        p.join(root.path, manifest.crop, manifest.version),
      );
      if (await finalDir.exists()) await finalDir.delete(recursive: true);
      await finalDir.parent.create(recursive: true);
      await staging.rename(finalDir.path);

      // One version per crop on the handset, and it is the one just asked for.
      //
      // Two reasons. Storage: these are ~45 MB each, and a phone with 2 GB
      // free cannot accumulate history. Correctness: `_scan` resolves a crop to
      // its highest version number, so leaving the old directory in place made
      // a deliberate rollback silently keep serving the newer pack - the
      // operator would see "installed 1.0.0" and the farmer would still be
      // scanning with the 1.0.1 weights they were trying to withdraw.
      await _pruneOtherVersions(manifest.crop, manifest.version);

      // Only a crop pack changes what the farmer's scanner points at.
      if (manifest.isCrop) await setActive(manifest.crop);
      await _scan(force: true);
      report('done', total, total, '');
      final installedPack = _installed[manifest.crop];
      if (installedPack == null) {
        throw PackException('Pack installed but could not be read back.');
      }
      if (installedPack.version != manifest.version) {
        throw PackException(
          'Installed ${manifest.version} but ${installedPack.version} is still '
          'active. Refusing to report success on the wrong pack.',
        );
      }
      return installedPack;
    } finally {
      if (await staging.exists()) {
        try {
          await staging.delete(recursive: true);
        } catch (_) {
          // Best effort: a leftover staging dir costs disk, not correctness.
        }
      }
    }
  }

  /// Deletes every other installed version of [crop], leaving only [keep].
  /// Best effort per directory: a file the OS will not let go of costs disk,
  /// not correctness, and must not fail an install that already succeeded.
  Future<void> _pruneOtherVersions(String crop, String keep) async {
    final root = await _packsRootOrNull();
    if (root == null) return;
    final cropDir = Directory(p.join(root.path, crop));
    if (!await cropDir.exists()) return;
    for (final d in cropDir.listSync().whereType<Directory>()) {
      if (p.basename(d.path) == keep) continue;
      try {
        await d.delete(recursive: true);
      } catch (_) {}
    }
  }

  Future<PackManifest> _fetchManifest(String relPath) async {
    final base = await catalogBase();
    final uri = Uri.parse('$base/$relPath');
    final res = await _client.get(uri).timeout(const Duration(seconds: 20));
    if (res.statusCode != 200) {
      throw PackException('Manifest returned ${res.statusCode} from $uri.');
    }
    return PackManifest.fromJson(
      jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<List<int>> _download(Uri url) async {
    final res = await _client.get(url).timeout(const Duration(minutes: 10));
    if (res.statusCode != 200) {
      throw PackException('${url.path} returned ${res.statusCode}.');
    }
    return res.bodyBytes;
  }

  /// Removes an installed crop. Used when the farmer changes crop and wants
  /// the storage back.
  Future<void> remove(String crop) async {
    final root = await _packsRootOrNull();
    if (root == null) return;
    final dir = Directory(p.join(root.path, crop));
    if (await dir.exists()) await dir.delete(recursive: true);
    await _scan(force: true);
  }
}
