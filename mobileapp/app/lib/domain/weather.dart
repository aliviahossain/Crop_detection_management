/// Port of the deterministic synthetic feed in backend/app/services/weather.py.
///
/// This is what makes risk forecasting work in airplane mode. The server falls
/// back to this feed when it has no API key or no network; on the handset it is
/// the *primary* source until a real forecast has been prefetched and cached.
///
/// Determinism is the contract: the same location and timestamp always produce
/// the same weather, so a demo is reproducible and a test can assert on it.
/// The seed is SHA-256 of the rounded coordinates plus the date/hour, matching
/// `_seeded_unit` exactly - a different hash here would mean the phone and the
/// server disagree about the forecast for the same field.
library;

import 'dart:convert';
import 'dart:math' as math;

import 'package:crypto/crypto.dart';

import 'num_compat.dart';

class HourPoint {
  const HourPoint({
    required this.ts,
    required this.tempC,
    required this.humidity,
    required this.rainfallMm,
    this.isForecast = false,
  });

  final DateTime ts;
  final double tempC;
  final double humidity;
  final double rainfallMm;
  final bool isForecast;

  Map<String, dynamic> toJson() => {
        'ts': ts.toUtc().toIso8601String(),
        'temp_c': tempC,
        'humidity': humidity,
        'rainfall_mm': rainfallMm,
        'is_forecast': isForecast,
      };
}

class WeatherSeries {
  const WeatherSeries({
    required this.lat,
    required this.lon,
    required this.points,
    required this.source,
    required this.synthetic,
    this.realHours = 0,
    this.warnings = const [],
  });

  final double lat;
  final double lon;
  final List<HourPoint> points;
  final String source;
  final bool synthetic;
  final int realHours;
  final List<String> warnings;

  Map<String, dynamic> toJson() => {
        'lat': lat,
        'lon': lon,
        'source': source,
        'synthetic': synthetic,
        'real_hours': realHours,
        'total_hours': points.length,
        'warnings': warnings,
        'points': points.map((p) => p.toJson()).toList(),
      };
}

/// Deterministic pseudo-random in [0,1). Mirrors `_seeded_unit`: SHA-256 of
/// the parts joined by '|', first 8 hex digits over 0xFFFFFFFF.
double seededUnit(List<Object> parts) {
  final raw = parts.map((p) => p.toString()).join('|');
  final digest = sha256.convert(utf8.encode(raw)).toString();
  final head = int.parse(digest.substring(0, 8), radix: 16);
  return head / 0xFFFFFFFF;
}

/// Python writes floats like `18.5` and ints like `18` for the same value.
/// The seed strings embed rounded coordinates, so they must be formatted the
/// same way Python's `round(lat, 2)` would appear inside an f-string.
String _pyNumStr(double v) {
  final r = pyRound(v, 2);
  if (r == r.roundToDouble()) return '${r.toInt()}.0';
  return r.toString();
}

String _dateIso(DateTime ts) {
  final u = ts.toUtc();
  return '${u.year.toString().padLeft(4, '0')}-'
      '${u.month.toString().padLeft(2, '0')}-'
      '${u.day.toString().padLeft(2, '0')}';
}

/// Python `datetime.isoformat()` for a tz-aware UTC datetime renders as
/// `2026-09-16T08:00:00+00:00`.
String _tsIso(DateTime ts) {
  final u = ts.toUtc();
  final d = _dateIso(u);
  final t = '${u.hour.toString().padLeft(2, '0')}:'
      '${u.minute.toString().padLeft(2, '0')}:'
      '${u.second.toString().padLeft(2, '0')}';
  return '${d}T$t+00:00';
}

/// Hourly synthetic series, `hours` long, starting at `start`.
List<HourPoint> synthSeries({
  required DateTime start,
  required int hours,
  required double lat,
  required double lon,
  required DateTime now,
}) {
  final pts = <HourPoint>[];
  final latS = _pyNumStr(lat);
  final lonS = _pyNumStr(lon);

  for (var i = 0; i < hours; i++) {
    final ts = start.add(Duration(hours: i)).toUtc();
    final daySeed = seededUnit([latS, lonS, _dateIso(ts)]);
    final hourSeed = seededUnit([latS, lonS, _tsIso(ts)]);

    // Diurnal cycle: min ~05:00, max ~15:00.
    final phase = math.cos((ts.hour - 15) / 24 * 2 * math.pi);
    final baseMean = 20.0 + 4.0 * daySeed; // 20-24 C daily mean
    final amplitude = 5.0 + 3.0 * daySeed; // 5-8 C swing
    final temp = baseMean + amplitude * phase + (hourSeed - 0.5) * 1.2;

    // RH runs opposite to temperature; some days are humid spells.
    final humidDay = daySeed > 0.55;
    final baseRh = humidDay ? 78.0 : 58.0;
    var humidity = baseRh - 18.0 * phase + (hourSeed - 0.5) * 6.0;
    humidity = math.max(25.0, math.min(99.0, humidity));

    var rain = 0.0;
    if (humidDay && hourSeed > 0.88) {
      rain = pyRound(2.0 + 6.0 * hourSeed, 1);
    }

    pts.add(HourPoint(
      ts: ts,
      tempC: pyRound(temp, 1),
      humidity: pyRound(humidity, 1),
      rainfallMm: rain,
      isForecast: ts.isAfter(now),
    ));
  }
  return pts;
}

/// The series the risk engine consumes: `pastDays` back to `forecastDays`
/// ahead, hourly. Offline this is entirely synthetic and says so.
WeatherSeries getSeries({
  required double lat,
  required double lon,
  int pastDays = 7,
  int forecastDays = 3,
  DateTime? now,
  List<HourPoint> cached = const [],
}) {
  final at = (now ?? DateTime.now().toUtc()).toUtc();
  final anchor = DateTime.utc(at.year, at.month, at.day, at.hour);
  final start = anchor.subtract(Duration(days: pastDays));
  final hours = (pastDays + forecastDays) * 24;

  if (cached.isEmpty) {
    return WeatherSeries(
      lat: lat,
      lon: lon,
      points: synthSeries(
          start: start, hours: hours, lat: lat, lon: lon, now: anchor),
      source: 'synthetic',
      synthetic: true,
      realHours: 0,
      warnings: const [
        'No cached observations on this device - running on the deterministic '
            'synthetic feed. Connect once to store a real forecast.',
      ],
    );
  }

  // Cached real hours win; synthetic fills every gap so the models always see
  // a continuous series (they count hours above a threshold, and a hole would
  // silently under-count).
  final byHour = <String, HourPoint>{
    for (final p in cached) _tsIso(p.ts): p,
  };
  final synth = synthSeries(
      start: start, hours: hours, lat: lat, lon: lon, now: anchor);
  var real = 0;
  final merged = <HourPoint>[];
  for (final s in synth) {
    final hit = byHour[_tsIso(s.ts)];
    if (hit != null) {
      merged.add(hit);
      real++;
    } else {
      merged.add(s);
    }
  }

  return WeatherSeries(
    lat: lat,
    lon: lon,
    points: merged,
    source: real == merged.length ? 'cache' : 'cache+synthetic',
    synthetic: real == 0,
    realHours: real,
    warnings: real == merged.length
        ? const []
        : [
            '$real of ${merged.length} hours came from stored observations; '
                'the remainder is synthetic backfill.',
          ],
  );
}
