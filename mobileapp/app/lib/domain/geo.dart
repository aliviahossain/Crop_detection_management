/// Port of backend/app/services/geo.py.
///
/// Validated against mobileapp/fixtures/geo.json.
library;

import 'dart:math' as math;

/// ~0.05 deg latitude is ~5.5 km - coarse enough to cluster sparse field
/// reports, fine enough to point an officer at a village group.
const double kDefaultCellDeg = 0.05;
const double kEarthRadiusKm = 6371.0;

/// Grid-cell id for a coordinate, or null if either axis is missing.
///
/// Uses floor, not truncation. `(-1.02 / 0.05).toInt()` is -20 in Dart but
/// Python's `math.floor` gives -21; every coordinate in Maharashtra is
/// positive so a truncating port passes every manual test and silently
/// mis-buckets the moment the app is used south of the equator or west of
/// Greenwich.
String? geoCell(double? lat, double? lon, {double sizeDeg = kDefaultCellDeg}) {
  if (lat == null || lon == null) return null;
  final latI = (lat / sizeDeg).floor();
  final lonI = (lon / sizeDeg).floor();
  return '${_g(sizeDeg)}:$latI:$lonI';
}

/// Centre of a cell, as (lat, lon).
({double lat, double lon}) cellCenter(String cell) {
  final parts = cell.split(':');
  final size = double.parse(parts[0]);
  final latI = int.parse(parts[1]);
  final lonI = int.parse(parts[2]);
  return (lat: (latI + 0.5) * size, lon: (lonI + 0.5) * size);
}

/// Great-circle distance in kilometres.
double haversineKm(double lat1, double lon1, double lat2, double lon2) {
  final p1 = _rad(lat1);
  final p2 = _rad(lat2);
  final dp = p2 - p1;
  final dl = _rad(lon2 - lon1);
  final a = math.sin(dp / 2) * math.sin(dp / 2) +
      math.cos(p1) * math.cos(p2) * math.sin(dl / 2) * math.sin(dl / 2);
  return 2 * kEarthRadiusKm * math.asin(math.sqrt(a));
}

double _rad(double deg) => deg * math.pi / 180.0;

/// Mirrors Python's `'%g' % size` formatting of the cell-size prefix, so cell
/// ids generated here are byte-identical to ones generated server-side
/// (0.05 -> "0.05", 0.25 -> "0.25", 1.0 -> "1").
String _g(double v) {
  if (v == v.roundToDouble() && v.abs() < 1e6) {
    return v.toInt().toString();
  }
  var s = v.toString();
  if (s.contains('.')) {
    s = s.replaceFirst(RegExp(r'0+$'), '');
    s = s.replaceFirst(RegExp(r'\.$'), '');
  }
  return s;
}
