/// Derives the officer endpoints from the bundled synthetic dataset.
///
/// Ports the aggregations in `backend/app/routers/{dashboard,review,hotspots,
/// followup,sensors}.py` closely enough that the same React pages render the
/// same way against either source. Where the server would run SQL, this runs a
/// fold over 120 in-memory rows, which at that size is not worth a database.
///
/// The point of computing rather than shipping precomputed numbers: the period
/// selector and the district filter do something. A static blob would give
/// four figures that never move, which is obvious to anyone who clicks.
library;

import '../domain/geo.dart';
import '../domain/taxonomy.dart';
import 'demo_dataset.dart';

/// Weighted-count cut-offs for the map's colour ramp, from hotspots.py.
const Map<String, double> kIntensityBands = {
  'severe': 8.0,
  'high': 4.0,
  'moderate': 2.0,
};

/// An unreviewed case is real signal but unconfirmed, so it counts for less
/// than a confirmed one rather than not at all.
const double kUnverifiedWeightDemo = 0.4;

String _bandFor(double weighted) {
  if (weighted >= kIntensityBands['severe']!) return 'severe';
  if (weighted >= kIntensityBands['high']!) return 'high';
  if (weighted >= kIntensityBands['moderate']!) return 'moderate';
  return 'low';
}

String _isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-'
    '${d.month.toString().padLeft(2, '0')}-'
    '${d.day.toString().padLeft(2, '0')}';

class DemoApi {
  DemoApi(this.data);

  final DemoDataset data;

  // ------------------------------------------------------------------
  // Dashboard
  // ------------------------------------------------------------------

  Map<String, dynamic> dashboardSummary(int days, String? district) {
    final rows = data.casesWithin(days, district: district);
    final total = rows.length;

    var fromImage = 0;
    var escalated = 0;
    var pending = 0;
    var confirmed = 0;
    final byClass = <String, int>{};
    final byRisk = <String, int>{'low': 0, 'medium': 0, 'high': 0};
    final highRiskDistricts = <String, int>{};

    for (final c in rows) {
      if (c.source == 'image') fromImage++;
      if (c.escalate) escalated++;
      if (c.reviewStatus == 'pending') pending++;
      if (c.reviewStatus == 'confirmed') confirmed++;
      // Reviewed cases count by the expert label, the rest by the prediction.
      byClass[c.effectiveClass] = (byClass[c.effectiveClass] ?? 0) + 1;
      byRisk[c.riskLevel] = (byRisk[c.riskLevel] ?? 0) + 1;
      if (c.riskLevel == 'high') {
        highRiskDistricts[c.district] = (highRiskDistricts[c.district] ?? 0) + 1;
      }
    }

    final classRows = byClass.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final districtRows = highRiskDistricts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));

    final overdue = data.followUps
        .where((f) => f.isPending && f.dueDate.isBefore(data.loadedAt))
        .length;
    final since = data.loadedAt.subtract(Duration(days: days));
    final activeDevices = data.readings
        .where((r) => !r.recordedAt.isBefore(since))
        .map((r) => r.deviceId)
        .toSet()
        .length;

    return {
      'window_days': days,
      'district': district,
      'cases': {
        'total': total,
        'from_image': fromImage,
        'proactive_risk_only': total - fromImage,
        'escalated': escalated,
        'pending_review': pending,
        'expert_confirmed': confirmed,
        'escalation_rate':
            total == 0 ? null : _round(escalated / total, 3),
      },
      'by_class': [
        for (final e in classRows)
          {
            'class_key': e.key,
            'display': displayName(e.key),
            'count': e.value,
            'share': total == 0 ? 0 : _round(e.value / total, 3),
          }
      ],
      'by_risk_level': byRisk,
      'high_risk_districts': [
        for (final e in districtRows)
          {'district': e.key, 'high_risk_cases': e.value}
      ],
      'follow_ups_overdue': overdue,
      'active_sensor_devices': activeDevices,
      'demo': true,
    };
  }

  Map<String, dynamic> dashboardTrend(int days, String? district, String? classKey) {
    final since = data.loadedAt.subtract(Duration(days: days));
    // Seed every day in the window first, so the chart draws a continuous axis
    // rather than skipping days that happen to have no cases.
    final series = <String, Map<String, dynamic>>{};
    for (var i = 0; i <= days; i++) {
      final day = _isoDay(since.add(Duration(days: i)));
      series[day] = {
        'date': day,
        'total': 0,
        'confirmed': 0,
        'escalated': 0,
        'high_risk': 0,
      };
    }

    for (final c in data.casesWithin(days, district: district)) {
      if (classKey != null &&
          classKey.isNotEmpty &&
          c.effectiveClass != classKey) {
        continue;
      }
      final row = series[_isoDay(c.createdAt)];
      if (row == null) continue;
      row['total'] = (row['total'] as int) + 1;
      if (c.isReviewed) row['confirmed'] = (row['confirmed'] as int) + 1;
      if (c.escalate) row['escalated'] = (row['escalated'] as int) + 1;
      if (c.riskLevel == 'high') {
        row['high_risk'] = (row['high_risk'] as int) + 1;
      }
    }

    return {
      'days': days,
      'class_key': classKey,
      'series': series.values.toList(),
      'demo': true,
    };
  }

  Map<String, dynamic> dashboardDistricts() {
    final counts = <String, int>{};
    for (final c in data.cases) {
      counts[c.district] = (counts[c.district] ?? 0) + 1;
    }
    final rows = counts.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return {
      'districts': [
        for (final e in rows) {'district': e.key, 'cases': e.value}
      ],
      'demo': true,
    };
  }

  // ------------------------------------------------------------------
  // Review
  // ------------------------------------------------------------------

  /// `list[CaseOut]` - a JSON array, because that is what the page indexes into.
  List<Map<String, dynamic>> reviewQueue({
    int limit = 60,
    bool onlyEscalated = false,
  }) {
    final rows = [
      for (final c in data.cases)
        if (c.reviewStatus == 'pending' && (!onlyEscalated || c.escalate)) c
    ]..sort((a, b) {
        // Escalated first, then oldest first: the queue is a work list, and the
        // case that has waited longest is the one most likely to have gone cold.
        if (a.escalate != b.escalate) return a.escalate ? -1 : 1;
        return a.createdAt.compareTo(b.createdAt);
      });
    return [
      for (final c in rows.take(limit)) c.toJson()
    ];
  }

  Map<String, dynamic>? reviewCase(int id) {
    for (final c in data.cases) {
      if (c.id == id) return c.toJson();
    }
    return null;
  }

  Map<String, dynamic> accuracy() {
    var reviewed = 0;
    var confirmed = 0;
    final perClassReviewed = <String, int>{};
    final perClassConfirmed = <String, int>{};

    for (final c in data.cases) {
      if (!c.isReviewed) continue;
      reviewed++;
      perClassReviewed[c.predictedClass] =
          (perClassReviewed[c.predictedClass] ?? 0) + 1;
      if (c.reviewStatus == 'confirmed') {
        confirmed++;
        perClassConfirmed[c.predictedClass] =
            (perClassConfirmed[c.predictedClass] ?? 0) + 1;
      }
    }
    final pending =
        data.cases.where((c) => c.reviewStatus == 'pending').length;

    final keys = perClassReviewed.keys.toList()..sort();
    return {
      'reviewed': reviewed,
      'confirmed': confirmed,
      'corrected': reviewed - confirmed,
      'rejected': 0,
      'pending': pending,
      'field_accuracy': reviewed == 0 ? null : _round(confirmed / reviewed, 3),
      'per_class': [
        for (final k in keys)
          {
            'predicted_class': k,
            'display': displayName(k),
            'reviewed': perClassReviewed[k],
            'confirmed': perClassConfirmed[k] ?? 0,
            'accuracy': _round(
                (perClassConfirmed[k] ?? 0) / perClassReviewed[k]!, 3),
          }
      ],
      'retraining_samples_pending_export': reviewed,
      'demo': true,
    };
  }

  // ------------------------------------------------------------------
  // Hotspots
  // ------------------------------------------------------------------

  Map<String, dynamic> hotspots(int days, double cellSizeDeg, String? district) {
    final rows = data.casesWithin(days, district: district);
    final cells = <String, Map<String, dynamic>>{};

    for (final c in rows) {
      // Healthy cases are not pressure. Counting them would dilute exactly the
      // cells an officer is looking for.
      if (!isActionable(c.effectiveClass)) continue;
      final cell = geoCell(c.latitude, c.longitude, sizeDeg: cellSizeDeg);
      if (cell == null) continue;
      final entry = cells.putIfAbsent(
        cell,
        () => {
          'geo_cell': cell,
          'cell_size_deg': cellSizeDeg,
          'confirmed_cases': 0,
          'unverified_cases': 0,
          'districts': <String>{},
          'classes': <String, int>{},
        },
      );
      if (c.isReviewed) {
        entry['confirmed_cases'] = (entry['confirmed_cases'] as int) + 1;
      } else {
        entry['unverified_cases'] = (entry['unverified_cases'] as int) + 1;
      }
      (entry['districts'] as Set<String>).add(c.district);
      final classes = entry['classes'] as Map<String, int>;
      classes[c.effectiveClass] = (classes[c.effectiveClass] ?? 0) + 1;
    }

    final features = <Map<String, dynamic>>[];
    for (final entry in cells.values) {
      final confirmed = entry['confirmed_cases'] as int;
      final unverified = entry['unverified_cases'] as int;
      final weighted = confirmed + unverified * kUnverifiedWeightDemo;
      final centre = cellCenter(entry['geo_cell'] as String);
      final classes = entry['classes'] as Map<String, int>;
      final top = classes.entries.toList()
        ..sort((a, b) => b.value.compareTo(a.value));
      features.add({
        'geo_cell': entry['geo_cell'],
        'cell_size_deg': entry['cell_size_deg'],
        'latitude': centre.lat,
        'longitude': centre.lon,
        'confirmed_cases': confirmed,
        'unverified_cases': unverified,
        'weighted_count': _round(weighted, 3),
        'intensity': _bandFor(weighted),
        'districts': (entry['districts'] as Set<String>).toList()..sort(),
        'top_class': top.isEmpty ? null : top.first.key,
        'top_class_display': top.isEmpty ? null : displayName(top.first.key),
      });
    }
    features.sort((a, b) =>
        (b['weighted_count'] as double).compareTo(a['weighted_count'] as double));

    return {
      'window_days': days,
      'cell_size_deg': cellSizeDeg,
      'unverified_weight': kUnverifiedWeightDemo,
      'total_cells': features.length,
      'total_confirmed':
          features.fold<int>(0, (s, f) => s + (f['confirmed_cases'] as int)),
      'total_unverified':
          features.fold<int>(0, (s, f) => s + (f['unverified_cases'] as int)),
      'cells': features,
      'demo': true,
    };
  }

  Map<String, dynamic> hotspotPoints(int days, String? district) {
    final rows = data.casesWithin(days, district: district);
    final points = <Map<String, dynamic>>[];
    var confirmed = 0;
    var unverified = 0;
    for (final c in rows) {
      if (!isActionable(c.effectiveClass)) continue;
      final isConfirmed = c.isReviewed;
      if (isConfirmed) {
        confirmed++;
      } else {
        unverified++;
      }
      points.add({
        'latitude': c.latitude,
        'longitude': c.longitude,
        'weight': isConfirmed ? 1.0 : kUnverifiedWeightDemo,
        'class_key': c.effectiveClass,
        'confirmed': isConfirmed,
      });
    }
    return {
      'window_days': days,
      'unverified_weight': kUnverifiedWeightDemo,
      'severe_threshold': kIntensityBands['severe'],
      'total_confirmed': confirmed,
      'total_unverified': unverified,
      'total_points': points.length,
      'points': points,
      'demo': true,
    };
  }

  // ------------------------------------------------------------------
  // Follow-ups and sensors
  // ------------------------------------------------------------------

  List<Map<String, dynamic>> followUps({int limit = 100, bool? pendingOnly}) {
    final rows = [
      for (final f in data.followUps)
        if (pendingOnly != true || f.isPending) f
    ]..sort((a, b) => a.dueDate.compareTo(b.dueDate));
    return [for (final f in rows.take(limit)) f.toJson()];
  }

  Map<String, dynamic> followUpStats(int days) {
    final since = data.loadedAt.subtract(Duration(days: days));
    final counts = <String, int>{};
    for (final f in data.followUps) {
      if (f.createdAt.isBefore(since)) continue;
      counts[f.outcome] = (counts[f.outcome] ?? 0) + 1;
    }
    final closed = counts.entries
        .where((e) => e.key != 'pending')
        .fold<int>(0, (s, e) => s + e.value);
    final improved = (counts['resolved'] ?? 0) + (counts['improving'] ?? 0);
    final overdue = data.followUps
        .where((f) => f.isPending && f.dueDate.isBefore(data.loadedAt))
        .length;
    return {
      'window_days': days,
      'counts': counts,
      'closed': closed,
      'overdue': overdue,
      'improvement_rate': closed == 0 ? null : _round(improved / closed, 3),
      'demo': true,
    };
  }

  List<Map<String, dynamic>> sensors({int limit = 200}) {
    final rows = [...data.readings]
      ..sort((a, b) => b.recordedAt.compareTo(a.recordedAt));
    return [for (final r in rows.take(limit)) r.toJson()];
  }

  Map<String, dynamic> sensorSummary(int days, String metric) {
    final since = data.loadedAt.subtract(Duration(days: days));
    final cells = <String, List<double>>{};
    final cellDistricts = <String, Set<String>>{};
    for (final r in data.readings) {
      if (r.recordedAt.isBefore(since)) continue;
      if (r.metric != metric) continue;
      final cell = r.geoCell;
      if (cell == null) continue;
      cells.putIfAbsent(cell, () => []).add(r.value);
      cellDistricts.putIfAbsent(cell, () => <String>{}).add(r.district);
    }
    final out = <Map<String, dynamic>>[];
    for (final e in cells.entries) {
      final centre = cellCenter(e.key);
      final sum = e.value.fold<double>(0, (s, v) => s + v);
      out.add({
        'geo_cell': e.key,
        'latitude': centre.lat,
        'longitude': centre.lon,
        'readings': e.value.length,
        'mean': _round(sum / e.value.length, 2),
        'max': e.value.reduce((a, b) => a > b ? a : b),
        'districts': cellDistricts[e.key]!.toList()..sort(),
      });
    }
    out.sort((a, b) => (b['mean'] as double).compareTo(a['mean'] as double));
    return {
      'metric': metric,
      'window_days': days,
      'cells': out,
      'demo': true,
    };
  }
}

double _round(double v, int places) {
  final f = <int, double>{2: 100.0, 3: 1000.0}[places] ?? 1000.0;
  return (v * f).roundToDouble() / f;
}
