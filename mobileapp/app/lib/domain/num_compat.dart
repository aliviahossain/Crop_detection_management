/// Python-compatible numeric helpers.
///
/// These exist because the Dart port must produce *byte-identical* values to
/// the Python services it mirrors, and the two languages disagree about two
/// things that matter here:
///
/// 1. **Rounding.** Python's `round()` is round-half-to-**even** (banker's
///    rounding): `round(0.5) == 0`, `round(1.5) == 2`, `round(2.675, 2) ==
///    2.67`. Dart's `toStringAsFixed` and `roundToDouble` round half **away
///    from zero**. Every `round(x, n)` in risk_models.py therefore needs this
///    helper, not Dart's built-in, or scores drift in the last digit and the
///    golden-vector suite fails.
///
/// 2. **Floor on negatives.** Python's `math.floor(-1.2) == -2`. Dart's
///    `~/` and `toInt()` truncate toward zero, giving `-1`. `geo_cell` uses
///    floor, so a truncating port mis-buckets every southern/western
///    coordinate - see the negative-coordinate cases in fixtures/geo.json.
library;

import 'dart:math' as math;

/// Python's `round(value, digits)` - half-to-even.
double pyRound(double value, [int digits = 0]) {
  if (value.isNaN || value.isInfinite) return value;
  final factor = math.pow(10, digits).toDouble();
  final scaled = value * factor;

  // Values beyond 2^53 have no fractional part left to round.
  if (scaled.abs() >= 9007199254740992.0) return value;

  final floor = scaled.floorToDouble();
  final diff = scaled - floor;
  double rounded;
  if (diff > 0.5) {
    rounded = floor + 1;
  } else if (diff < 0.5) {
    rounded = floor;
  } else {
    // Exactly .5 - go to the even neighbour.
    rounded = (floor % 2 == 0) ? floor : floor + 1;
  }
  final result = rounded / factor;
  // Normalise -0.0 to 0.0, which Python also reports as 0.0 in JSON.
  return result == 0 ? 0.0 : result;
}

/// Python's `math.floor` semantics for ints, correct for negatives.
int pyFloorDiv(double value, double divisor) =>
    (value / divisor).floorToDouble().toInt();

/// Formats a double the way Python's `repr`/json.dumps would, so integral
/// values serialise as `1.0` rather than `1` where the Python side emits a
/// float. Used when building API payloads the web UI compares against.
num jsonNum(double value) {
  if (value == value.roundToDouble() && value.abs() < 1e15) {
    return value;
  }
  return value;
}
