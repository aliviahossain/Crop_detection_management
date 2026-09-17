/// The pack format, as the phone reads it.
///
/// Mirrors what `mobileapp/tools/build_pack.py` writes. A crop is a
/// downloadable pack, not an app release: weights, the thresholds tuned for
/// those weights, the taxonomy naming their classes and the KB pages that turn
/// a class into advice all version together, or not at all.
library;

class PackFile {
  const PackFile({required this.path, required this.bytes, required this.sha256});

  final String path;
  final int bytes;
  final String sha256;

  static PackFile fromJson(Map<String, dynamic> j) => PackFile(
        path: j['path'] as String,
        bytes: (j['bytes'] as num).toInt(),
        sha256: (j['sha256'] as String).toLowerCase(),
      );

  Map<String, dynamic> toJson() =>
      {'path': path, 'bytes': bytes, 'sha256': sha256};
}

class PackManifest {
  const PackManifest({
    required this.packFormat,
    required this.crop,
    required this.version,
    this.kind = 'crop',
    this.title,
    required this.builtAt,
    required this.minAppVersion,
    required this.classes,
    required this.files,
    required this.totalBytes,
    this.signature,
  });

  final int packFormat;
  final String crop;
  final String version;

  /// `crop` feeds the farmer's diagnosis and advisory path. `detector` feeds
  /// only a lab scanner and advises nothing, so it must never be picked as the
  /// active crop - installing one used to hijack potato detection, because
  /// "most recently installed" was the whole rule.
  final String kind;
  final String? title;

  bool get isCrop => kind != 'detector';
  final String builtAt;
  final String minAppVersion;
  final List<String> classes;
  final List<PackFile> files;
  final int totalBytes;
  final String? signature;

  static PackManifest fromJson(Map<String, dynamic> j) => PackManifest(
        packFormat: (j['pack_format'] as num?)?.toInt() ?? 0,
        crop: j['crop'] as String,
        version: j['version'] as String,
        kind: j['kind'] as String? ?? 'crop',
        title: j['title'] as String?,
        builtAt: j['built_at'] as String? ?? '',
        minAppVersion: j['min_app_version'] as String? ?? '0.0.0',
        classes: ((j['classes'] as List?) ?? const []).cast<String>(),
        files: ((j['files'] as List?) ?? const [])
            .map((f) => PackFile.fromJson((f as Map).cast<String, dynamic>()))
            .toList(),
        totalBytes: (j['total_bytes'] as num?)?.toInt() ?? 0,
        signature: j['signature'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'pack_format': packFormat,
        'kind': kind,
        'title': title,
        'crop': crop,
        'version': version,
        'built_at': builtAt,
        'min_app_version': minAppVersion,
        'classes': classes,
        'files': files.map((f) => f.toJson()).toList(),
        'total_bytes': totalBytes,
        'signature': signature,
      };
}

/// One crop offered by the catalogue, with the versions on the server.
class CatalogCrop {
  const CatalogCrop({
    required this.crop,
    required this.latest,
    required this.versions,
    this.kind = 'crop',
    this.title,
  });

  final String crop;
  final String latest;
  final List<CatalogVersion> versions;
  final String kind;
  final String? title;

  bool get isCrop => kind != 'detector';

  CatalogVersion? get latestVersion {
    for (final v in versions) {
      if (v.version == latest) return v;
    }
    return versions.isEmpty ? null : versions.first;
  }

  static CatalogCrop fromJson(Map<String, dynamic> j) => CatalogCrop(
        crop: j['crop'] as String,
        kind: j['kind'] as String? ?? 'crop',
        title: j['title'] as String?,
        latest: j['latest'] as String? ?? '',
        versions: ((j['versions'] as List?) ?? const [])
            .map((v) => CatalogVersion.fromJson((v as Map).cast<String, dynamic>()))
            .toList(),
      );
}

class CatalogVersion {
  const CatalogVersion({
    required this.version,
    required this.totalBytes,
    required this.minAppVersion,
    required this.classes,
    required this.manifestPath,
  });

  final String version;
  final int totalBytes;
  final String minAppVersion;
  final List<String> classes;

  /// Relative to the catalogue root, e.g. `potato/1.0.0/manifest.json`.
  final String manifestPath;

  static CatalogVersion fromJson(Map<String, dynamic> j) => CatalogVersion(
        version: j['version'] as String,
        totalBytes: (j['total_bytes'] as num?)?.toInt() ?? 0,
        minAppVersion: j['min_app_version'] as String? ?? '0.0.0',
        classes: ((j['classes'] as List?) ?? const []).cast<String>(),
        manifestPath: j['manifest'] as String? ?? '',
    );
}

/// A pack that is installed and verified on this device.
class InstalledPack {
  const InstalledPack({required this.manifest, required this.dir});

  final PackManifest manifest;

  /// Absolute directory holding the payload files.
  final String dir;

  String get crop => manifest.crop;
  String get version => manifest.version;
}

/// Compares dotted versions numerically, so 1.10.0 sorts above 1.9.0 where a
/// string compare would get it backwards.
int compareVersions(String a, String b) {
  final pa = a.split('.');
  final pb = b.split('.');
  for (var i = 0; i < (pa.length > pb.length ? pa.length : pb.length); i++) {
    final x = i < pa.length ? (int.tryParse(pa[i]) ?? 0) : 0;
    final y = i < pb.length ? (int.tryParse(pb[i]) ?? 0) : 0;
    if (x != y) return x.compareTo(y);
  }
  return 0;
}
