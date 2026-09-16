/// Port of backend/app/services/risk_models.py.
///
/// Published agronomic models - Smith Period, Beaumont Period, TOMCAST DSV and
/// degree-day accumulation. These are decades-old validated formulas that need
/// nothing but a weather series, which is exactly why the offline app can
/// forecast disease risk with the radio off: there is no model to download and
/// no server to ask.
///
/// Validated against mobileapp/fixtures/risk_models.json (40 cases).
library;

import 'num_compat.dart';
import 'weather.dart';

// Thresholds - single source of truth, mirrored from the Python constants and
// asserted against the fixture's `constants` block.
const double kSmithMinTempC = 10.0;
const double kSmithRhPct = 90.0;
const int kSmithRhHours = 11;
const int kSmithConsecutiveDays = 2;

const double kBeaumontMinTempC = 10.0;
const double kBeaumontRhPct = 75.0;
const int kBeaumontHours = 46;

const double kLeafWetnessRhPct = 90.0;

/// (tempLo, tempHi, wetness-hour cut points) -> severity = cut points met.
const List<(double, double, List<int>)> kTomcastTable = [
  (13.0, 17.9, [7, 16, 21]),
  (18.0, 20.9, [4, 9, 16, 23]),
  (21.0, 25.9, [3, 6, 13, 21]),
  (26.0, 29.9, [4, 9, 16, 23]),
];
const int kEarlyBlightDsvSprayThreshold = 15;
const int kEarlyBlightDsvWatchThreshold = 8;

class DaySummary {
  const DaySummary({
    required this.day,
    required this.tempMin,
    required this.tempMax,
    required this.tempMean,
    required this.rhMean,
    required this.hoursRhAbove90,
    required this.hoursRhAbove75,
    required this.wetnessHours,
    required this.wetnessMeanTemp,
    required this.rainfallMm,
  });

  /// ISO date, e.g. "2026-01-12".
  final String day;
  final double tempMin;
  final double tempMax;
  final double tempMean;
  final double rhMean;
  final int hoursRhAbove90;
  final int hoursRhAbove75;
  final int wetnessHours;
  final double? wetnessMeanTemp;
  final double rainfallMm;

  Map<String, dynamic> toJson() => {
        'day': day,
        'temp_min': tempMin,
        'temp_max': tempMax,
        'temp_mean': tempMean,
        'rh_mean': rhMean,
        'hours_rh_above_90': hoursRhAbove90,
        'hours_rh_above_75': hoursRhAbove75,
        'wetness_hours': wetnessHours,
        'wetness_mean_temp': wetnessMeanTemp,
        'rainfall_mm': rainfallMm,
      };
}

class ModelOutput {
  const ModelOutput({
    required this.name,
    required this.triggered,
    required this.score,
    this.detail = const {},
    this.explanation = '',
  });

  final String name;
  final bool triggered;
  final double score;
  final Map<String, dynamic> detail;
  final String explanation;

  Map<String, dynamic> toJson() => {
        'name': name,
        'triggered': triggered,
        'score': score,
        'detail': detail,
        'explanation': explanation,
      };
}

String _dayKey(DateTime ts) {
  final u = ts.toUtc();
  return '${u.year.toString().padLeft(4, '0')}-'
      '${u.month.toString().padLeft(2, '0')}-'
      '${u.day.toString().padLeft(2, '0')}';
}

/// Collapse an hourly series into the per-day aggregates the models need.
///
/// Leaf wetness is proxied by RH >= 90%, the standard substitute when no leaf
/// wetness sensor is present.
List<DaySummary> summariseDays(List<HourPoint> points) {
  final buckets = <String, List<HourPoint>>{};
  for (final p in points) {
    buckets.putIfAbsent(_dayKey(p.ts), () => []).add(p);
  }

  final days = buckets.keys.toList()..sort();
  final out = <DaySummary>[];
  for (final day in days) {
    final hrs = buckets[day]!;
    final temps = hrs.map((h) => h.tempC).toList();
    final hums = hrs.map((h) => h.humidity).toList();
    final wet = hrs.where((h) => h.humidity >= kLeafWetnessRhPct).toList();

    out.add(DaySummary(
      day: day,
      tempMin: pyRound(temps.reduce((a, b) => a < b ? a : b), 1),
      tempMax: pyRound(temps.reduce((a, b) => a > b ? a : b), 1),
      tempMean: pyRound(temps.reduce((a, b) => a + b) / temps.length, 1),
      rhMean: pyRound(hums.reduce((a, b) => a + b) / hums.length, 1),
      hoursRhAbove90: wet.length,
      hoursRhAbove75:
          hrs.where((h) => h.humidity >= kBeaumontRhPct).length,
      wetnessHours: wet.length,
      wetnessMeanTemp: wet.isEmpty
          ? null
          : pyRound(
              wet.map((h) => h.tempC).reduce((a, b) => a + b) / wet.length, 1),
      rainfallMm:
          pyRound(hrs.map((h) => h.rainfallMm).fold(0.0, (a, b) => a + b), 1),
    ));
  }
  return out;
}

/// A Smith Period = [kSmithConsecutiveDays] consecutive qualifying days.
/// A qualifying day has min temp >= 10 C and >= 11 hours at RH >= 90%.
ModelOutput smithPeriod(List<DaySummary> days) {
  final qualifying = days
      .map((d) =>
          d.tempMin >= kSmithMinTempC && d.hoursRhAbove90 >= kSmithRhHours)
      .toList();

  final periods = <Map<String, dynamic>>[];
  var run = 0;
  var bestRun = 0;
  for (var idx = 0; idx < qualifying.length; idx++) {
    run = qualifying[idx] ? run + 1 : 0;
    if (run > bestRun) bestRun = run;
    if (run >= kSmithConsecutiveDays) {
      final window = days.sublist(idx - run + 1, idx + 1);
      periods.add({
        'start': window.first.day,
        'end': window.last.day,
        'days': run,
      });
    }
  }

  // A "near miss" still matters agronomically - one qualifying day is a warning.
  var score = bestRun > 0
      ? (bestRun / kSmithConsecutiveDays).clamp(0.0, 1.0).toDouble()
      : 0.0;
  if (periods.isEmpty && bestRun == 1) score = 0.5;

  final triggered = periods.isNotEmpty;
  String explanation;
  if (triggered) {
    final last = periods.last;
    explanation =
        'Smith Period met: ${last['days']} consecutive days (${last['start']} '
        'to ${last['end']}) with minimum temperature >= $kSmithMinTempC C and '
        'at least $kSmithRhHours hours at RH >= $kSmithRhPct%. These are late '
        'blight infection conditions.';
  } else if (bestRun == 1) {
    explanation =
        'One qualifying day recorded (min temp and humidity thresholds met). '
        'A second consecutive day would complete a Smith Period.';
  } else {
    explanation =
        'No day met both the temperature and humidity-duration thresholds.';
  }

  return ModelOutput(
    name: 'smith_period',
    triggered: triggered,
    score: pyRound(score, 3),
    detail: {
      'periods': periods,
      'longest_run_days': bestRun,
      'qualifying_days': [
        for (var i = 0; i < days.length; i++)
          if (qualifying[i]) days[i].day,
      ],
      'thresholds': {
        'min_temp_c': kSmithMinTempC,
        'rh_pct': kSmithRhPct,
        'rh_hours': kSmithRhHours,
        'consecutive_days': kSmithConsecutiveDays,
      },
    },
    explanation: explanation,
  );
}

/// 46 consecutive hours at >= 10 C and RH >= 75%. Fires earlier and more often
/// than Smith - the amber pre-warning.
ModelOutput beaumontPeriod(List<HourPoint> points) {
  var best = 0;
  var run = 0;
  DateTime? startTs;
  DateTime? bestStart;

  for (final p in points) {
    if (p.tempC >= kBeaumontMinTempC && p.humidity >= kBeaumontRhPct) {
      if (run == 0) startTs = p.ts;
      run++;
      if (run > best) {
        best = run;
        bestStart = startTs;
      }
    } else {
      run = 0;
    }
  }

  final triggered = best >= kBeaumontHours;
  return ModelOutput(
    name: 'beaumont_period',
    triggered: triggered,
    score: pyRound((best / kBeaumontHours).clamp(0.0, 1.0).toDouble(), 3),
    detail: {
      'longest_run_hours': best,
      'required_hours': kBeaumontHours,
      'run_started': bestStart == null ? null : _isoUtc(bestStart),
    },
    explanation: triggered
        ? 'Beaumont Period met: $best consecutive hours above '
            '$kBeaumontMinTempC C with RH >= $kBeaumontRhPct%.'
        : 'Longest conducive run was ${best}h of the ${kBeaumontHours}h required.',
  );
}

String _isoUtc(DateTime ts) {
  final u = ts.toUtc();
  String p(int v, [int w = 2]) => v.toString().padLeft(w, '0');
  return '${p(u.year, 4)}-${p(u.month)}-${p(u.day)}T'
      '${p(u.hour)}:${p(u.minute)}:${p(u.second)}+00:00';
}

/// TOMCAST daily disease severity value, 0-4.
int _dsvForDay(DaySummary d) {
  if (d.wetnessHours == 0 || d.wetnessMeanTemp == null) return 0;
  final t = d.wetnessMeanTemp!;
  for (final (lo, hi, cuts) in kTomcastTable) {
    if (t >= lo && t <= hi) {
      return cuts.where((c) => d.wetnessHours >= c).length;
    }
  }
  return 0; // outside 13-30 C: sporulation is negligible
}

ModelOutput tomcastDsv(List<DaySummary> days) {
  final perDay = days
      .map((d) => {'day': d.day, 'dsv': _dsvForDay(d)})
      .toList();
  final total =
      perDay.fold<int>(0, (a, x) => a + (x['dsv'] as int));
  final triggered = total >= kEarlyBlightDsvSprayThreshold;
  final score =
      (total / kEarlyBlightDsvSprayThreshold).clamp(0.0, 1.0).toDouble();

  String explanation;
  if (triggered) {
    explanation =
        'Accumulated $total disease severity values (DSV) over ${days.length} '
        'days, at or above the $kEarlyBlightDsvSprayThreshold-DSV early blight '
        'spray threshold.';
  } else if (total >= kEarlyBlightDsvWatchThreshold) {
    explanation =
        'Accumulated $total DSV - approaching the '
        '$kEarlyBlightDsvSprayThreshold-DSV spray threshold. Scout fields now.';
  } else {
    explanation = 'Accumulated $total DSV - early blight pressure is low.';
  }

  return ModelOutput(
    name: 'tomcast_dsv',
    triggered: triggered,
    score: pyRound(score, 3),
    detail: {
      'total_dsv': total,
      'spray_threshold': kEarlyBlightDsvSprayThreshold,
      'watch_threshold': kEarlyBlightDsvWatchThreshold,
      'per_day': perDay,
    },
    explanation: explanation,
  );
}

class PestModel {
  const PestModel({
    required this.key,
    required this.display,
    required this.baseTempC,
    required this.upperTempC,
    required this.degreeDaysPerGeneration,
    required this.note,
  });

  final String key;
  final String display;
  final double baseTempC;
  final double upperTempC;
  final double degreeDaysPerGeneration;
  final String note;
}

const Map<String, PestModel> kPestModels = {
  'potato_tuber_moth': PestModel(
    key: 'potato_tuber_moth',
    display: 'Potato tuber moth (Phthorimaea operculella)',
    baseTempC: 10.0,
    upperTempC: 35.0,
    degreeDaysPerGeneration: 360.0,
    note: 'The major storage and field pest of potato in Maharashtra. Around '
        '360 degree-days above 10 C completes a generation; time pheromone-trap '
        'checks and any intervention to the emergence peak.',
  ),
  'aphid_vector': PestModel(
    key: 'aphid_vector',
    display: 'Aphid complex (virus vectors)',
    baseTempC: 4.4,
    upperTempC: 30.0,
    degreeDaysPerGeneration: 120.0,
    note: 'Aphids matter mainly as virus vectors in seed potato. Degree-day '
        'accumulation indicates flight activity build-up.',
  ),
};

/// Single-triangle degree-day accumulation with an upper cut-off.
ModelOutput degreeDays(List<DaySummary> days, PestModel pest) {
  var total = 0.0;
  final series = <Map<String, dynamic>>[];

  for (final d in days) {
    final tMax = d.tempMax < pest.upperTempC ? d.tempMax : pest.upperTempC;
    final tMin = d.tempMin > pest.baseTempC ? d.tempMin : pest.baseTempC;
    final dd = tMax > pest.baseTempC
        ? ((tMax + tMin) / 2 - pest.baseTempC).clamp(0.0, double.infinity)
        : 0.0;
    total += dd;
    series.add({'day': d.day, 'dd': pyRound(dd.toDouble(), 1)});
  }

  final generations = total / pest.degreeDaysPerGeneration;
  final triggered = generations >= 1.0;

  return ModelOutput(
    name: 'degree_days:${pest.key}',
    triggered: triggered,
    score: pyRound(generations.clamp(0.0, 1.0).toDouble(), 3),
    detail: {
      'pest': pest.key,
      'display': pest.display,
      'accumulated_dd': pyRound(total, 1),
      'dd_per_generation': pest.degreeDaysPerGeneration,
      'generations': pyRound(generations, 2),
      'base_temp_c': pest.baseTempC,
      'per_day': series,
      'note': pest.note,
    },
    explanation:
        '${pyRound(total, 1)} degree-days accumulated above ${pest.baseTempC} C '
        '(${pyRound(generations, 2)} of a generation). '
        '${triggered ? 'A generation is complete - expect an emergence peak and check traps.' : 'Emergence peak has not been reached yet.'}',
  );
}
