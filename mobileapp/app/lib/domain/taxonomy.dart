/// Port of backend/app/services/taxonomy.py.
///
/// The classes the deployed detector actually knows. Scope is POTATO ONLY with
/// three classes; adding a crop is a data job, not a code change - which on the
/// handset means shipping another crop pack, not another app release.
library;

class ClassInfo {
  const ClassInfo({
    required this.key,
    required this.display,
    required this.crop,
    required this.kind,
    required this.pathogen,
    required this.severity,
    required this.kbDoc,
    this.names = const {},
  });

  /// Model label - must match ml/data.yaml order.
  final String key;
  final String display;
  final String crop;

  /// disease | pest | healthy
  final String kind;
  final String? pathogen;

  /// none | moderate | high
  final String severity;
  final String kbDoc;
  final Map<String, String> names;

  Map<String, dynamic> toJson() => {
        'key': key,
        'display': display,
        'crop': crop,
        'kind': kind,
        'pathogen': pathogen,
        'severity': severity,
        'names': names,
      };
}

const String kCrop = 'potato';

/// Index order IS the model's class index order.
const List<ClassInfo> kClasses = [
  ClassInfo(
    key: 'potato_early_blight',
    display: 'Potato - Early Blight',
    crop: kCrop,
    kind: 'disease',
    pathogen: 'Alternaria solani',
    severity: 'moderate',
    kbDoc: 'potato_early_blight.md',
    names: {
      'mr': 'बटाटा - लवकर येणारा करपा',
      'hi': 'आलू - अगेती झुलसा',
      'bn': 'আলু - আগাম ধসা',
    },
  ),
  ClassInfo(
    key: 'potato_late_blight',
    display: 'Potato - Late Blight',
    crop: kCrop,
    kind: 'disease',
    pathogen: 'Phytophthora infestans',
    severity: 'high',
    kbDoc: 'potato_late_blight.md',
    names: {
      'mr': 'बटाटा - उशिरा येणारा करपा',
      'hi': 'आलू - पछेती झुलसा',
      'bn': 'আলু - নাবি ধসা',
    },
  ),
  ClassInfo(
    key: 'potato_healthy',
    display: 'Potato - Healthy',
    crop: kCrop,
    kind: 'healthy',
    pathogen: null,
    severity: 'none',
    kbDoc: 'potato_healthy.md',
    names: {
      'mr': 'बटाटा - निरोगी',
      'hi': 'आलू - स्वस्थ',
      'bn': 'আলু - সুস্থ',
    },
  ),
];

final List<String> kClassNames = [for (final c in kClasses) c.key];
final Map<String, ClassInfo> kByKey = {for (final c in kClasses) c.key: c};

/// Threats the risk engine forecasts but the image model does not detect.
/// Kept out of kClasses so they can never be returned as a detection.
const Map<String, Map<String, String>> kNonModelThreats = {
  'potato_tuber_moth': {
    'en': 'Potato tuber moth',
    'mr': 'बटाटा पोखरणारी अळी',
    'hi': 'आलू कंद कीट',
    'bn': 'আলুর মথ পোকা',
  },
  'aphid_vector': {
    'en': 'Aphid complex (virus vectors)',
    'mr': 'मावा किडी (विषाणू वाहक)',
    'hi': 'माहू कीट (विषाणु वाहक)',
    'bn': 'জাব পোকা (ভাইরাস বাহক)',
  },
};

ClassInfo? classFor(String? key) => key == null ? null : kByKey[key];

/// Localized name for anything the system can name: a model class or a
/// forecast-only threat.
String displayName(String? key, [String lang = 'en']) {
  final info = classFor(key);
  if (info != null) return info.names[lang] ?? info.display;
  final threat = kNonModelThreats[key];
  if (threat != null) return threat[lang] ?? threat['en']!;
  return key ?? 'unknown';
}

/// Healthy / unknown does not warrant a pesticide recommendation.
bool isActionable(String? key) {
  final info = classFor(key);
  return info != null && (info.kind == 'disease' || info.kind == 'pest');
}
