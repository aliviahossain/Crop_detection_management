/// Proves the forecasting path works with no network and no cached data - the
/// airplane-mode claim, asserted rather than demonstrated by hand.
///
/// Nothing here touches HTTP, the filesystem or a clock it does not control,
/// which is the point: if these pass, the same computation runs on a handset
/// with the radio off.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/domain/risk_models.dart';
import 'package:cropguard/domain/taxonomy.dart';
import 'package:cropguard/domain/triage.dart';
import 'package:cropguard/domain/weather.dart';

// Manchar, Pune - the demo location the web app opens on.
const double kLat = 18.9282;
const double kLon = 73.9285;

void main() {
  group('weather with no network or cache', () {
    test('produces a full hourly series from nothing', () {
      final s = getSeries(
        lat: kLat,
        lon: kLon,
        now: DateTime.utc(2026, 1, 12, 9),
      );
      // 7 days back + 3 forward, hourly.
      expect(s.points.length, (7 + 3) * 24);
      expect(s.synthetic, isTrue);
      expect(s.realHours, 0);
      // The honesty rule: it must SAY it is synthetic, not quietly pretend.
      expect(s.warnings, isNotEmpty);
      expect(s.source, 'synthetic');
    });

    test('is deterministic - same place and time, same weather', () {
      final a = getSeries(
          lat: kLat, lon: kLon, now: DateTime.utc(2026, 1, 12, 9));
      final b = getSeries(
          lat: kLat, lon: kLon, now: DateTime.utc(2026, 1, 12, 9));
      expect(a.points.map((p) => p.tempC).toList(),
          b.points.map((p) => p.tempC).toList());
      expect(a.points.map((p) => p.humidity).toList(),
          b.points.map((p) => p.humidity).toList());
    });

    test('different locations get different weather', () {
      final pune = getSeries(
          lat: kLat, lon: kLon, now: DateTime.utc(2026, 1, 12, 9));
      final nashik = getSeries(
          lat: 19.9975, lon: 73.7898, now: DateTime.utc(2026, 1, 12, 9));
      expect(pune.points.map((p) => p.tempC).toList(),
          isNot(nashik.points.map((p) => p.tempC).toList()));
    });

    test('values stay inside physically sane bounds', () {
      final s = getSeries(
          lat: kLat, lon: kLon, now: DateTime.utc(2026, 1, 12, 9));
      for (final p in s.points) {
        expect(p.humidity, inInclusiveRange(25.0, 99.0));
        expect(p.tempC, inInclusiveRange(0.0, 55.0));
        expect(p.rainfallMm, greaterThanOrEqualTo(0.0));
      }
    });
  });

  group('risk forecasting offline', () {
    late List<DaySummary> days;
    late WeatherSeries series;

    setUp(() {
      series =
          getSeries(lat: kLat, lon: kLon, now: DateTime.utc(2026, 1, 12, 9));
      days = summariseDays(series.points);
    });

    test('every published model returns a usable verdict', () {
      for (final m in [
        smithPeriod(days),
        beaumontPeriod(series.points),
        tomcastDsv(days),
        degreeDays(days, kPestModels['potato_tuber_moth']!),
        degreeDays(days, kPestModels['aphid_vector']!),
      ]) {
        expect(m.score, inInclusiveRange(0.0, 1.0), reason: m.name);
        expect(m.explanation, isNotEmpty, reason: m.name);
        expect(m.detail, isNotEmpty, reason: m.name);
      }
    });

    test('summarise_days covers the whole window', () {
      expect(days.length, greaterThanOrEqualTo(10));
      for (final d in days) {
        expect(d.tempMin, lessThanOrEqualTo(d.tempMax));
        expect(d.hoursRhAbove90, lessThanOrEqualTo(d.hoursRhAbove75));
      }
    });
  });

  group('triage offline', () {
    test('no bundled detector routes to a human, never to a guess', () {
      // This build ships no model, so /detect reports unavailable. The gate
      // must refuse self-treatment and refer, rather than naming a chemical.
      final r = evaluateTriage(modelAvailable: false);
      expect(r.escalate, isTrue);
      expect(r.selfTreatmentAllowed, isFalse);
      expect(r.referralLevel, 'block');
      expect(r.reasons.single['code'], 'model_unavailable');
    });

    test('healthy crop under high risk is a preventive window, not an alarm',
        () {
      final r = evaluateTriage(
        modelAvailable: true,
        predictedClass: 'potato_healthy',
        confidence: 0.95,
        detectionCount: 1,
        risk: const {
          'top_threat': 'potato_late_blight',
          'overall_level': 'high'
        },
      );
      expect(r.escalate, isFalse);
      expect(r.urgency, 'soon');
      expect(r.reasons.map((x) => x['code']), contains('preventive_window'));
    });
  });

  group('taxonomy offline', () {
    test('every class names itself in all four languages', () {
      for (final c in kClasses) {
        for (final lang in ['en', 'mr', 'hi', 'bn']) {
          final name = displayName(c.key, lang);
          expect(name, isNotEmpty);
          expect(name, isNot(c.key), reason: '${c.key} has no $lang name');
        }
      }
    });

    test('healthy is never actionable', () {
      expect(isActionable('potato_healthy'), isFalse);
      expect(isActionable('potato_late_blight'), isTrue);
      expect(isActionable(null), isFalse);
    });
  });
}
