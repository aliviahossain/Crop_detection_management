/// Runs the Dart safety gate against the Python-generated golden vectors.
///
/// Triage decides whether a farmer may act on the app's own diagnosis. On the
/// handset it runs with no server and no reviewer, so every branch and every
/// threshold boundary is pinned. A port that is off by one on
/// `confidence >= 0.55` changes who is told to buy a fungicide.
///
/// Regenerate with:  python mobileapp/tools/export_fixtures.py --write
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/domain/triage.dart';

/// Prose keys are warnings, not failures, in the Python comparator - the same
/// rule applies here so improving a farmer-facing message cannot break CI.
const Set<String> kProseKeys = {'message', 'action', 'explanation', 'why'};

Map<String, dynamic> _loadSuite(String name) {
  final file = File('../fixtures/$name.json');
  if (!file.existsSync()) {
    throw StateError('Missing ${file.absolute.path}. Run: '
        'python mobileapp/tools/export_fixtures.py --write');
  }
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

void main() {
  final suite = _loadSuite('triage');
  final cases = (suite['cases'] as List).cast<Map<String, dynamic>>();

  test('threshold agrees with the Python side', () {
    expect((suite['constants'] as Map)['low_confidence_threshold'],
        kLowConfidenceThreshold);
  });

  test('suite is non-trivial', () {
    expect(cases.length, greaterThanOrEqualTo(25));
  });

  for (final c in cases) {
    test('${c['id']}', () {
      final i = c['input'] as Map<String, dynamic>;
      final got = evaluateTriage(
        modelAvailable: i['model_available'] as bool,
        predictedClass: i['predicted_class'] as String?,
        confidence: (i['confidence'] as num?)?.toDouble(),
        risk: (i['risk'] as Map?)?.cast<String, dynamic>(),
        detectionCount: i['detection_count'] as int,
        failedTreatments: i['failed_treatments'] as int,
        severityFraction: (i['severity_fraction'] as num?)?.toDouble(),
      ).toJson();

      final want = c['expect'] as Map<String, dynamic>;

      // The decision fields - these are what actually gate a pesticide.
      expect(got['escalate'], want['escalate'], reason: 'escalate');
      expect(got['urgency'], want['urgency'], reason: 'urgency');
      expect(got['self_treatment_allowed'], want['self_treatment_allowed'],
          reason: 'self_treatment_allowed');
      expect(got['referral_level'], want['referral_level'],
          reason: 'referral_level');

      // Reason codes and their order: the UI renders them in sequence, and the
      // officer dashboard counts them, so order is part of the contract.
      final wantCodes =
          (want['reasons'] as List).map((r) => (r as Map)['code']).toList();
      final gotCodes =
          (got['reasons'] as List).map((r) => (r as Map)['code']).toList();
      expect(gotCodes, wantCodes, reason: 'reason codes / order');

      // Every reason must carry a non-empty message and action, even though
      // the wording itself is free to change.
      for (final r in got['reasons'] as List) {
        final m = r as Map;
        for (final k in kProseKeys.where(m.containsKey)) {
          expect(m[k], isNotEmpty, reason: 'reason ${m['code']} has empty $k');
        }
      }
    });
  }
}
