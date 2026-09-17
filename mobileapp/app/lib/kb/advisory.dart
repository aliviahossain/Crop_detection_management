/// Composes an advisory on-device, from retrieved knowledge-base text.
///
/// Port of the deterministic half of `backend/app/services/advisory.py`. The
/// server runs this as a LangGraph pipeline (retrieve, compose, safety,
/// localize); the same four steps are four function calls here, because a
/// graph runtime buys orchestration this does not need.
///
/// What is deliberately NOT ported: nothing generative. The server does not
/// have a model write the dose numbers either - it parses them out of reviewed
/// markdown tables, so the figures a farmer sprays by stay accountable to a
/// human-edited file that an agronomist can correct in a pull request. On a
/// handset that property matters more, not less: there is no one to escalate a
/// hallucinated dose to.
library;

import 'knowledge_base.dart';

const Map<String, int> kFollowUpDays = {
  'potato_late_blight': 5,
  'potato_early_blight': 7,
  'potato_healthy': 7,
  'potato_tuber_moth': 7,
  'aphid_vector': 7,
};
const int kDefaultFollowUpDays = 7;

const Map<String, List<String>> kImmediateActions = {
  'potato_late_blight': [
    'action.remove_infected',
    'action.stop_evening_irrigation',
    'action.earthing_up',
    'action.rotate_chemistry',
  ],
  'potato_early_blight': [
    'action.remove_infected',
    'action.scout',
    'action.rotate_chemistry',
  ],
  'potato_healthy': ['action.no_spray', 'action.scout', 'action.earthing_up'],
  'potato_tuber_moth': ['action.check_traps', 'action.earthing_up'],
  'aphid_vector': ['action.scout'],
};

const List<String> kSafetyBullets = [
  'safety.licensed_dealer',
  'safety.label_dose',
  'safety.ppe',
  'safety.wind',
  'safety.phi',
  'safety.container',
  'safety.children',
  'safety.poison_helpline',
];

final RegExp _tableRow = RegExp(r'^\|(.+)\|\s*$');
final RegExp _bulletPrefix = RegExp(r'^[-*]\s*');

/// Pulls `| Product | Dose | Notes |` rows out of a KB section.
///
/// Matches on table structure rather than on section titles: renaming a
/// heading, or adding a "Curative / systemic" block, must not silently drop
/// half the treatment options from a farmer's advisory.
List<Map<String, String>> parseDoseTable(String text) {
  final rows = <Map<String, String>>[];
  List<String>? header;
  for (final rawLine in text.split('\n')) {
    final line = rawLine.trim();
    final m = _tableRow.firstMatch(line);
    if (m == null) {
      header = null;
      continue;
    }
    final cells = m.group(1)!.split('|').map((c) => c.trim()).toList();
    // Separator row: only dashes, colons and spaces, and never empty.
    final isSeparator = cells.every((c) =>
        c.isNotEmpty && c.split('').every((ch) => ch == '-' || ch == ':' || ch == ' '));
    if (isSeparator) continue;
    if (header == null) {
      header = cells.map((c) => c.toLowerCase()).toList();
      continue;
    }
    final row = <String, String>{};
    for (var i = 0; i < cells.length && i < header.length; i++) {
      row[header[i]] = cells[i];
    }
    final product = row['product'] ?? '';
    if (product.isNotEmpty) {
      rows.add({
        'product': product,
        'dose': row['dose'] ?? '',
        'notes': row['notes'] ?? '',
      });
    }
  }
  return rows;
}

/// The pack's translation catalogue, with the server's fallback order:
/// requested language, then English, then the key itself so a missing string
/// is visible rather than blank.
class AdvisoryStrings {
  AdvisoryStrings(this._byLang);

  final Map<String, Map<String, String>> _byLang;

  static AdvisoryStrings fromPackJson(Map<String, dynamic> strings) {
    final adv = (strings['advisory'] as Map?)?.cast<String, dynamic>() ?? {};
    return AdvisoryStrings({
      for (final e in adv.entries)
        e.key: (e.value as Map).map((k, v) => MapEntry('$k', '$v')),
    });
  }

  String t(String key, String lang, {Map<String, String> args = const {}}) {
    var text = _byLang[lang]?[key] ?? _byLang['en']?[key] ?? key;
    args.forEach((k, v) => text = text.replaceAll('{$k}', v));
    return text;
  }
}

/// The plain-language opening line.
///
/// Port of `_summary_paragraph`. The server will use an LLM for this sentence
/// when one is configured and fall back to the same templates otherwise;
/// on-device there is only the template, which is no loss because nothing
/// safety-critical lives in this string - the dose table and the triage gate
/// are both built elsewhere, from reviewed sources.
String _summaryParagraph(
  AdvisoryInput input,
  String Function(String, {Map<String, String> args}) tr,
  String Function(String, String) displayFor,
) {
  final lang = input.language;
  final classKey = input.classKey;
  final conf = input.confidence;
  String base;

  if (!input.modelAvailable) {
    base = tr('diag.unavailable');
  } else if (!input.hasDetection) {
    // Proactive path: a forecast with no photograph. Never phrase a forecast
    // as a diagnosis - a farmer acting on "detected" would be acting on
    // nothing.
    base = tr('diag.forecast_only');
  } else if (classKey == 'potato_healthy') {
    base = tr('diag.healthy');
  } else if (classKey != null) {
    base = tr('diag.detected', args: {
      'disease': displayFor(classKey, lang),
      'confidence': '${((conf ?? 0) * 100).round()}%',
    });
  } else {
    base = tr('diag.uncertain');
  }

  if (!(input.triage['self_treatment_allowed'] as bool? ?? true)) {
    base = '$base ${tr('diag.uncertain')}';
  }

  final threats = (input.risk['threats'] as List?) ?? const [];
  if (threats.isNotEmpty) {
    final top = (threats.first as Map).cast<String, dynamic>();
    base = '$base ${tr('risk.sentence', args: {
          'threat': displayFor(top['key'] as String, lang),
          'level': tr('risk.${top['level']}'),
        })}';
    // Smith firing is the single most actionable weather fact for potato, so
    // it earns its own sentence rather than being buried in the model list.
    final smithFired = threats.any((th) =>
        (((th as Map)['models'] as List?) ?? const []).any((m) =>
            (m as Map)['name'] == 'smith_period' && m['triggered'] == true));
    if (smithFired) base = '$base ${tr('risk.smith_fired')}';
  }
  return base;
}

class AdvisoryInput {
  const AdvisoryInput({
    required this.classKey,
    required this.language,
    this.confidence,
    this.question,
    this.risk = const {},
    this.triage = const {},
    this.modelAvailable = true,
    this.hasDetection = true,
  });

  final String? classKey;
  final String language;
  final double? confidence;
  final String? question;
  final Map<String, dynamic> risk;
  final Map<String, dynamic> triage;

  /// Whether a crop pack is installed at all.
  final bool modelAvailable;

  /// Whether this advisory follows an actual photograph, or is a weather
  /// forecast with no image behind it.
  final bool hasDetection;
}

/// Builds the advisory body. `displayFor` names a class in the farmer's
/// language; it is passed in so this file does not need the taxonomy.
Map<String, dynamic> composeAdvisory({
  required AdvisoryInput input,
  required KnowledgeBase kb,
  required AdvisoryStrings strings,
  required String Function(String key, String lang) displayFor,
  DateTime? now,
}) {
  final lang = input.language;
  final classKey = input.classKey;
  String tr(String k, {Map<String, String> args = const {}}) =>
      strings.t(k, lang, args: args);

  // Retrieval: the class key plus whatever the farmer asked, so a typed
  // question steers the references without displacing the class.
  final query = [
    if (classKey != null) classKey.replaceAll('_', ' '),
    if (input.question != null && input.question!.isNotEmpty) input.question!,
  ].join(' ').trim();
  final hits = kb.search(
    query.isEmpty ? 'potato management' : query,
    k: 5,
    classFilter: classKey == null ? null : [classKey],
  );

  final riskLevel = input.risk['overall_level'] as String?;
  final selfTreatmentAllowed =
      input.triage['self_treatment_allowed'] as bool? ?? true;

  // Immediate actions
  var actionKeys = List<String>.from(kImmediateActions[classKey ?? ''] ?? const []);
  if (classKey == 'potato_healthy' && riskLevel == 'high') {
    actionKeys = [
      'action.protectant',
      'action.scout',
      'action.stop_evening_irrigation',
    ];
  }
  if (actionKeys.isEmpty) actionKeys = ['action.scout'];

  // Chemical options, only where a chemical response is actually justified.
  final chemical = <Map<String, String>>[];
  final String gate;
  final actionable = classKey != null &&
      classKey != 'potato_healthy' &&
      classKey.isNotEmpty;
  if (!selfTreatmentAllowed) {
    // The triage gate said a human must confirm first. Withholding the dose
    // table is the whole point of that gate, so it is honoured here rather
    // than shown with a warning next to it.
    gate = 'withheld_pending_expert_confirmation';
  } else if (actionable || riskLevel == 'high') {
    final target = actionable ? classKey : input.risk['top_threat'] as String?;
    for (final section in kb.sectionsForClass(target ?? '')) {
      chemical.addAll(parseDoseTable(section.text));
    }
    // No dose table is not a data gap: for tuber moth and aphids the knowledge
    // base deliberately recommends monitoring and cultural control instead of
    // a routine spray.
    gate = chemical.isEmpty ? 'non_chemical_first' : 'recommended';
  } else {
    gate = 'not_required';
  }

  // Cultural practice, verbatim from the reviewed KB.
  final cultural = <String>[];
  for (final section in kb.sectionsForClass(classKey ?? '')) {
    final title = section.section.toLowerCase();
    if (title.contains('cultural') ||
        title.contains('preventive') ||
        title.contains('keep it healthy')) {
      for (final line in section.text.split('\n')) {
        final t = line.trim();
        if (t.startsWith('-') || t.startsWith('*')) {
          cultural.add(t.replaceFirst(_bulletPrefix, '').trim());
        }
      }
    }
  }

  final followUpDays = kFollowUpDays[classKey ?? ''] ?? kDefaultFollowUpDays;
  final due = (now ?? DateTime.now().toUtc()).add(Duration(days: followUpDays));
  final dueIso = '${due.year.toString().padLeft(4, '0')}-'
      '${due.month.toString().padLeft(2, '0')}-'
      '${due.day.toString().padLeft(2, '0')}';

  final summary = _summaryParagraph(input, tr, displayFor);

  return {
    'language': lang,
    'summary': summary,
    'sections': [
      {
        'key': 'immediate',
        'heading': tr('heading.immediate'),
        'items': [for (final k in actionKeys) tr(k)],
      },
      {
        'key': 'cultural',
        'heading': tr('heading.cultural'),
        'items': cultural.take(8).toList(),
      },
    ],
    'chemical': {
      'heading': tr('heading.chemical'),
      'status': gate,
      'status_note': const {
            'withheld_pending_expert_confirmation': 'chemical.withheld',
            'not_required': 'chemical.not_required',
            'non_chemical_first': 'chemical.non_chemical_first',
          }[gate] !=
              null
          ? tr(const {
              'withheld_pending_expert_confirmation': 'chemical.withheld',
              'not_required': 'chemical.not_required',
              'non_chemical_first': 'chemical.non_chemical_first',
            }[gate]!)
          : null,
      'options': chemical,
      'disclaimer': tr('note.verify_local'),
      'rotation_note': tr('action.rotate_chemistry'),
    },
    'follow_up': {
      'heading': tr('heading.followup'),
      'days': followUpDays,
      'date': dueIso,
      'text': tr('followup.scheduled', args: {'date': dueIso}),
      'why': tr('followup.why'),
    },
    'safety': {
      'heading': tr('heading.safety'),
      'items': [for (final k in kSafetyBullets) tr(k)],
    },
    'references': [
      for (final h in hits.take(4))
        {
          'title': h['title'],
          'section': h['section'],
          'doc_id': h['doc_id'],
          'score': h['score'],
          'excerpt': (h['text'] as String).length > 600
              ? (h['text'] as String).substring(0, 600)
              : h['text'],
          'sources': h['sources'] ?? const [],
        }
    ],
    'offline': true,
  };
}
