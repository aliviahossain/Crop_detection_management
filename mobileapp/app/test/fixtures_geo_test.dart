/// Runs the Dart geo implementation against the golden vectors generated from
/// the Python service. This is the whole point of mobileapp/fixtures: two
/// languages, one definition of correct.
///
/// Regenerate with:  python mobileapp/tools/export_fixtures.py --write
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/domain/geo.dart';
import 'package:cropguard/domain/num_compat.dart';

/// Same tolerance the Python comparator uses (fixture_lib.FLOAT_TOL).
const double kFloatTol = 1e-6;

Map<String, dynamic> _loadSuite(String name) {
  // Tests run with CWD = the Flutter app root (mobileapp/app).
  final file = File('../fixtures/$name.json');
  if (!file.existsSync()) {
    throw StateError(
      'Missing ${file.absolute.path}. Run: '
      'python mobileapp/tools/export_fixtures.py --write',
    );
  }
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

void main() {
  final suite = _loadSuite('geo');
  final cases = (suite['cases'] as List).cast<Map<String, dynamic>>();

  test('fixture suite is present and non-trivial', () {
    expect(suite['source'], 'backend/app/services/geo.py');
    expect(cases.length, greaterThanOrEqualTo(18));
  });

  group('geo_cell', () {
    for (final c in cases.where((c) => c['fn'] == 'geo_cell')) {
      test('${c['id']} - ${c['why']}', () {
        final input = c['input'] as Map<String, dynamic>;
        final expected = c['expect'] as Map<String, dynamic>;

        final cell = geoCell(
          (input['lat'] as num?)?.toDouble(),
          (input['lon'] as num?)?.toDouble(),
          sizeDeg: (input['size_deg'] as num).toDouble(),
        );
        expect(cell, expected['cell'], reason: 'cell id mismatch');

        if (expected.containsKey('center_lat')) {
          final centre = cellCenter(cell!);
          expect(
            pyRound(centre.lat, 9),
            closeTo((expected['center_lat'] as num).toDouble(), kFloatTol),
          );
          expect(
            pyRound(centre.lon, 9),
            closeTo((expected['center_lon'] as num).toDouble(), kFloatTol),
          );
        }
      });
    }
  });

  group('haversine_km', () {
    for (final c in cases.where((c) => c['fn'] == 'haversine_km')) {
      test('${c['id']} - ${c['why']}', () {
        final i = c['input'] as Map<String, dynamic>;
        final got = haversineKm(
          (i['lat1'] as num).toDouble(),
          (i['lon1'] as num).toDouble(),
          (i['lat2'] as num).toDouble(),
          (i['lon2'] as num).toDouble(),
        );
        final want = ((c['expect'] as Map)['km'] as num).toDouble();
        expect(pyRound(got, 6), closeTo(want, kFloatTol));
      });
    }
  });
}
