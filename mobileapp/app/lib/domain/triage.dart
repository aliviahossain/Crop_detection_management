/// Port of backend/app/services/triage.py.
///
/// The safety gate: decides whether a case is safe to self-treat or must go to
/// a human. Deliberately conservative - when the system is unsure it says so
/// and hands the case over rather than naming a pesticide.
///
/// On the handset this runs with no server to fall back on and no reviewer
/// watching, which is exactly why every branch and every boundary value is
/// pinned in mobileapp/fixtures/triage.json (25 cases).
library;

import 'taxonomy.dart';

/// Mirrors settings.low_confidence_threshold. Asserted against the fixture's
/// `constants` block so a change on one side cannot silently diverge.
const double kLowConfidenceThreshold = 0.55;

class TriageResult {
  const TriageResult({
    required this.escalate,
    required this.urgency,
    this.reasons = const [],
    this.selfTreatmentAllowed = true,
    this.referralLevel,
  });

  final bool escalate;

  /// routine | soon | urgent
  final String urgency;
  final List<Map<String, String>> reasons;
  final bool selfTreatmentAllowed;

  /// village | block | district | laboratory
  final String? referralLevel;

  Map<String, dynamic> toJson() => {
        'escalate': escalate,
        'urgency': urgency,
        'self_treatment_allowed': selfTreatmentAllowed,
        'referral_level': referralLevel,
        'reasons': reasons,
      };
}

Map<String, String> _reason(String code, String message, String action) =>
    {'code': code, 'message': message, 'action': action};

/// Python's `f"{x:.0%}"`.
String _pct(double v) => '${(v * 100).round()}%';

/// [severityFraction] is the share of the field reported affected, 0-1.
TriageResult evaluateTriage({
  required bool modelAvailable,
  String? predictedClass,
  double? confidence,
  Map<String, dynamic>? risk,
  int detectionCount = 0,
  int failedTreatments = 0,
  double? severityFraction,
}) {
  final reasons = <Map<String, String>>[];
  var escalate = false;
  var selfTreat = true;
  var urgency = 'routine';
  String? referral;

  // 1. No model, no diagnosis. Never guess a pesticide from nothing.
  if (!modelAvailable) {
    return TriageResult(
      escalate: true,
      urgency: 'soon',
      selfTreatmentAllowed: false,
      referralLevel: 'block',
      reasons: [
        _reason(
          'model_unavailable',
          'The image detection model is not available on this deployment, so '
              'no automated diagnosis was made.',
          'Send the photograph to your Taluka Agriculture Officer or KVK for a '
              'human diagnosis. Do not spray on the basis of this app alone.',
        ),
      ],
    );
  }

  // 2. Model ran but saw nothing above threshold.
  if (predictedClass == null || detectionCount == 0) {
    escalate = true;
    selfTreat = false;
    referral = 'village';
    urgency = 'soon';
    reasons.add(_reason(
      'no_detection',
      'The model found no symptom it recognises above the confidence '
          'threshold. This may mean a healthy crop, a poor photograph, or a '
          'problem outside the three potato classes it was trained on.',
      'Retake the photo in daylight, filling the frame with the affected leaf. '
          'If symptoms are visible to you, refer the case to an extension officer.',
    ));
  }

  // 3. Low confidence - the core safety rule.
  if (confidence != null && confidence < kLowConfidenceThreshold) {
    escalate = true;
    selfTreat = false;
    referral ??= 'village';
    if (urgency == 'routine') urgency = 'soon';
    reasons.add(_reason(
      'low_confidence',
      'Model confidence is ${_pct(confidence)}, below the '
          '${_pct(kLowConfidenceThreshold)} threshold required to recommend a '
          'chemical treatment.',
      'Treat the diagnosis as provisional. Get it confirmed by an extension '
          'officer before buying or applying any pesticide.',
    ));
  }

  // 4. Image and weather disagree - classic misdiagnosis trap.
  if (risk != null && predictedClass != null && isActionable(predictedClass)) {
    final top = risk['top_threat'];
    final topLevel = risk['overall_level'];
    if (top != null && top != predictedClass && topLevel == 'high') {
      escalate = true;
      reasons.add(_reason(
        'conflicting_signals',
        'The image was classified as ${displayName(predictedClass)}, but '
            'weather conditions indicate HIGH risk of '
            '${displayName(top as String)} instead.',
        'Have an extension officer inspect the field before choosing a '
            'chemistry - the wrong product here wastes money and leaves residue '
            'for no benefit.',
      ));
    }
  }

  // 5. High weather risk with a healthy-looking crop is a preventive decision.
  if (risk != null &&
      predictedClass == 'potato_healthy' &&
      risk['overall_level'] == 'high') {
    urgency = 'soon';
    reasons.add(_reason(
      'preventive_window',
      'No symptoms were detected, but the weather risk forecast is HIGH. This '
          'is the window where a protectant spray prevents an epidemic instead '
          'of chasing it.',
      'Follow the preventive advisory and scout the field within 48 hours. '
          'This is a judgement call worth confirming with your Krishi Sahayak.',
    ));
  }

  // 6. Repeated treatment failure suggests resistance, not a bigger dose.
  if (failedTreatments >= 2) {
    escalate = true;
    selfTreat = false;
    referral = 'laboratory';
    urgency = 'urgent';
    reasons.add(_reason(
      'treatment_failure',
      '$failedTreatments follow-ups recorded the problem as unchanged or '
          'worsened after treatment.',
      'Do not repeat the same spray. This pattern suggests fungicide '
          'resistance or a misdiagnosis and needs laboratory confirmation '
          'through your KVK.',
    ));
  }

  // 7. Field-scale severity is an outbreak, not an individual problem.
  if (severityFraction != null && severityFraction >= 0.25) {
    escalate = true;
    referral = 'district';
    urgency = 'urgent';
    reasons.add(_reason(
      'high_severity',
      'About ${_pct(severityFraction)} of the field is reported affected.',
      'Report to the Taluka Agriculture Officer today. At this scale a '
          'coordinated response is needed, and neighbouring fields should be '
          'surveyed.',
    ));
  }

  // 8. A confident high-severity disease is urgent even if self-treatable.
  final info = classFor(predictedClass);
  if (info != null &&
      info.severity == 'high' &&
      confidence != null &&
      confidence >= kLowConfidenceThreshold) {
    urgency = 'urgent';
    reasons.add(_reason(
      'fast_moving_disease',
      '${info.display} can destroy an unprotected crop within 7-10 days once '
          'conditions are favourable.',
      'Begin the recommended management today, and inform neighbouring farmers '
          'so they can protect their fields.',
    ));
  }

  if (reasons.isEmpty) {
    reasons.add(_reason(
      'clear_case',
      'Confident diagnosis with no conflicting signals.',
      'Follow the advisory below and complete the scheduled follow-up.',
    ));
  }

  return TriageResult(
    escalate: escalate,
    urgency: urgency,
    selfTreatmentAllowed: selfTreat,
    referralLevel: referral,
    reasons: reasons,
  );
}
