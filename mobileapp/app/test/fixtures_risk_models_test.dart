/// Runs the Dart agronomic models against the Python-generated golden vectors.
///
/// Each case carries the raw hourly series, so summariseDays is pinned
/// alongside each model - a port that gets the per-day bucket boundaries or
/// the RH>=90 leaf-wetness proxy wrong fails here rather than in a field.
///
/// Regenerate with:  python mobileapp/tools/export_fixtures.py --write
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/domain/risk_models.dart';
import 'package:cropguard/domain/weather.dart';

const double kFloatTol = 1e-6;

/// Prose differences are warnings in the Python comparator, not failures -
/// someone improving a farmer-facing message must not break the build. Same
/// rule here: these keys are skipped when comparing.
const Set<String> kProseKeys = {
  'explanation',
  'message',
  'action',
  'note',
  'display',
  'why',
};

Map<String, dynamic> _loadSuite(String name) {
  final file = File('../fixtures/$name.json');
  if (!file.existsSync()) {
    throw StateError('Missing ${file.absolute.path}. Run: '
        'python mobileapp/tools/export_fixtures.py --write');
  }
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

List<HourPoint> _points(List<dynamic> raw) => raw
    .cast<Map<String, dynamic>>()
    .map((p) => HourPoint(
          ts: DateTime.parse(p['ts'] as String),
          tempC: (p['temp_c'] as num).toDouble(),
          humidity: (p['humidity'] as num).toDouble(),
          rainfallMm: (p['rainfall_mm'] as num).toDouble(),
          isForecast: p['is_forecast'] as bool,
        ))
    .toList();

/// Structural comparison mirroring fixture_lib.compare, minus the prose keys.
void _expectMatches(dynamic want, dynamic got, String path) {
  final leaf = path.split('.').last.split('[').first;
  if (kProseKeys.contains(leaf)) return;

  if (want is Map) {
    expect(got, isA<Map>(), reason: '$path: expected an object');
    final g = got as Map;
    expect({...want.keys}, equals({...g.keys}), reason: '$path: key sets differ');
    for (final k in want.keys) {
      _expectMatches(want[k], g[k], '$path.$k');
    }
    return;
  }
  if (want is List) {
    expect(got, isA<List>(), reason: '$path: expected a list');
    final g = got as List;
    expect(g.length, want.length, reason: '$path: length differs');
    for (var i = 0; i < want.length; i++) {
      _expectMatches(want[i], g[i], '$path[$i]');
    }
    return;
  }
  if (want is bool || got is bool) {
    expect(got, want, reason: path);
    return;
  }
  if (want is num && got is num) {
    expect(got.toDouble(), closeTo(want.toDouble(), kFloatTol),
        reason: path);
    return;
  }
  expect(got, want, reason: path);
}

Map<String, dynamic> _run(String fn, List<HourPoint> pts) {
  final days = summariseDays(pts);
  if (fn == 'summarise_days') {
    return {'days': days.map((d) => d.toJson()).toList()};
  }
  if (fn == 'smith_period') return smithPeriod(days).toJson();
  if (fn == 'beaumont_period') return beaumontPeriod(pts).toJson();
  if (fn == 'tomcast_dsv') return tomcastDsv(days).toJson();
  if (fn.startsWith('degree_days:')) {
    final pest = kPestModels[fn.split(':')[1]]!;
    return degreeDays(days, pest).toJson();
  }
  throw ArgumentError('unknown fn $fn');
}

void main() {
  final suite = _loadSuite('risk_models');
  final cases = (suite['cases'] as List).cast<Map<String, dynamic>>();
  final consts = suite['constants'] as Map<String, dynamic>;

  test('constants agree with the Python side', () {
    // A threshold changed on one side and not the other must fail loudly here
    // rather than silently diverge in the field.
    expect(consts['smith_min_temp_c'], kSmithMinTempC);
    expect(consts['smith_rh_pct'], kSmithRhPct);
    expect(consts['smith_rh_hours'], kSmithRhHours);
    expect(consts['smith_consecutive_days'], kSmithConsecutiveDays);
    expect(consts['beaumont_min_temp_c'], kBeaumontMinTempC);
    expect(consts['beaumont_rh_pct'], kBeaumontRhPct);
    expect(consts['beaumont_hours'], kBeaumontHours);
    expect(consts['leaf_wetness_rh_pct'], kLeafWetnessRhPct);
    expect(consts['early_blight_dsv_spray_threshold'],
        kEarlyBlightDsvSprayThreshold);
    expect(consts['early_blight_dsv_watch_threshold'],
        kEarlyBlightDsvWatchThreshold);

    final pests = consts['pest_models'] as Map<String, dynamic>;
    for (final entry in pests.entries) {
      final want = entry.value as Map<String, dynamic>;
      final got = kPestModels[entry.key]!;
      expect(got.baseTempC, want['base_temp_c']);
      expect(got.upperTempC, want['upper_temp_c']);
      expect(got.degreeDaysPerGeneration, want['degree_days_per_generation']);
    }
  });

  test('suite is non-trivial', () {
    expect(cases.length, greaterThanOrEqualTo(40));
  });

  for (final c in cases) {
    test('${c['id']}', () {
      final pts = _points((c['input'] as Map)['hours'] as List);
      final got = _run(c['fn'] as String, pts);
      _expectMatches(c['expect'], got, c['id'] as String);
    }, );
  }
}
