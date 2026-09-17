/// Port of backend/app/services/knowledge_base.py - the lexical half.
///
/// The server picks between ChromaDB vector search and a dependency-free BM25
/// retriever. On the handset there is no choice to make: BM25 is the whole
/// implementation. That is not a downgrade so much as an honest fit. The corpus
/// is six markdown pages of agronomy, the queries are a class key plus a few
/// field observations, and the retrieval unit is a markdown section. Lexical
/// scoring over a corpus that small, with vocabulary that controlled, is what
/// the server falls back to anyway - and it costs no model download, no
/// embedding step and no megabytes.
///
/// Scoring must match the Python BM25 exactly, because the same query on the
/// phone and on the officer's desk should surface the same dose table. The
/// constants, the tokenizer, the stopword list and the class boost are all
/// copied rather than re-derived, and the fixtures pin the result.
library;

import 'dart:math' as math;

final RegExp _tokenRe = RegExp(r'[a-z0-9][a-z0-9\-\.]*');

const Set<String> kStopwords = {
  'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'is', 'are', 'for', 'on',
  'with', 'as', 'at', 'by', 'it', 'this', 'that', 'be', 'from', 'not', 'no',
  'do', 'does', 'can', 'if', 'then', 'than', 'so', 'we', 'you', 'your',
};

List<String> tokenize(String text) => _tokenRe
    .allMatches(text.toLowerCase())
    .map((m) => m.group(0)!)
    .where((t) => !kStopwords.contains(t) && t.length > 1)
    .toList();

class Chunk {
  const Chunk({
    required this.docId,
    required this.chunkId,
    required this.title,
    required this.section,
    required this.text,
    this.classes = const [],
    this.kind = '',
    this.crop = '',
    this.sources = const [],
  });

  final String docId;
  final String chunkId;
  final String title;
  final String section;
  final String text;
  final List<String> classes;
  final String kind;
  final String crop;
  final List<String> sources;

  Map<String, dynamic> toJson() => {
        'doc_id': docId,
        'chunk_id': chunkId,
        'title': title,
        'section': section,
        'classes': classes,
        'kind': kind,
        'sources': sources,
      };
}

// ----------------------------------------------------------------------
// Parsing
// ----------------------------------------------------------------------

/// Enough YAML for our front matter. The Python side prefers PyYAML and falls
/// back to this same subset; the KB only ever uses scalars, inline lists and
/// block lists, so a full parser would be a dependency bought for nothing.
Map<String, dynamic> parseMinimalYaml(String raw) {
  final out = <String, dynamic>{};
  String? currentListKey;
  for (final line in raw.split('\n')) {
    if (line.trim().isEmpty) continue;
    final trimmedLeft = line.trimLeft();
    if (trimmedLeft.startsWith('- ') && currentListKey != null) {
      (out[currentListKey] as List).add(trimmedLeft.substring(2).trim());
      continue;
    }
    final idx = line.indexOf(':');
    if (idx < 0) continue;
    final key = line.substring(0, idx).trim();
    final value = line.substring(idx + 1).trim();
    if (value.isEmpty) {
      currentListKey = key;
      out[key] = <String>[];
    } else if (value.startsWith('[') && value.endsWith(']')) {
      out[key] = value
          .substring(1, value.length - 1)
          .split(',')
          .map((v) => v.trim())
          .where((v) => v.isNotEmpty)
          .toList();
      currentListKey = null;
    } else {
      out[key] = value;
      currentListKey = null;
    }
  }
  return out;
}

({Map<String, dynamic> meta, String body}) parseFrontMatter(String raw) {
  if (!raw.startsWith('---')) return (meta: <String, dynamic>{}, body: raw);
  // Split on the first two '---' exactly as Python's str.split(sep, 2) does.
  final first = raw.indexOf('---');
  final second = raw.indexOf('---', first + 3);
  if (second < 0) return (meta: <String, dynamic>{}, body: raw);
  final metaRaw = raw.substring(first + 3, second);
  final body = raw.substring(second + 3);
  return (meta: parseMinimalYaml(metaRaw), body: body);
}

final RegExp _headingRe = RegExp(r'^#{1,3} ');

/// Chunk on markdown headings. Sections are the natural retrieval unit --
/// "Chemical management" should come back whole, dose table and all.
List<({String title, String text})> splitSections(String body) {
  final sections = <({String title, String text})>[];
  var currentTitle = 'Overview';
  var buffer = <String>[];

  void flush() {
    if (buffer.any((l) => l.trim().isNotEmpty)) {
      sections.add((title: currentTitle, text: buffer.join('\n').trim()));
    }
  }

  for (final line in body.split('\n')) {
    if (_headingRe.hasMatch(line)) {
      flush();
      currentTitle = line.replaceFirst(RegExp(r'^#+'), '').trim();
      buffer = <String>[];
    } else {
      buffer.add(line);
    }
  }
  flush();
  return sections;
}

List<String> _stringList(Object? v) {
  if (v == null) return const [];
  if (v is String) return [v];
  if (v is List) return v.map((e) => '$e').toList();
  return const [];
}

/// Turns one markdown page into its chunks. `name` is the file name, used as
/// the id fallback exactly as the Python uses `path.stem`.
List<Chunk> chunksForDocument(String name, String raw) {
  final parsed = parseFrontMatter(raw);
  final meta = parsed.meta;
  final stem = name.endsWith('.md') ? name.substring(0, name.length - 3) : name;
  final docId = (meta['id'] ?? stem).toString();
  final title = (meta['title'] ?? stem).toString();
  final classes = _stringList(meta['classes']);
  final sources = _stringList(meta['sources']);
  final sections = splitSections(parsed.body);
  return [
    for (var i = 0; i < sections.length; i++)
      Chunk(
        docId: docId,
        chunkId: '$docId#$i',
        title: title,
        section: sections[i].title,
        text: sections[i].text,
        classes: classes,
        kind: (meta['kind'] ?? '').toString(),
        crop: (meta['crop'] ?? '').toString(),
        sources: sources,
      ),
  ];
}

// ----------------------------------------------------------------------
// BM25
// ----------------------------------------------------------------------

class ScoredChunk {
  const ScoredChunk(this.chunk, this.score, this.order);
  final Chunk chunk;
  final double score;

  /// Position in the corpus. Carried only so ties can be broken the way
  /// Python breaks them; see the sort in [Bm25Retriever.search].
  final int order;
}

class Bm25Retriever {
  Bm25Retriever(this.chunks)
      : _docs = chunks.map((c) => tokenize('${c.title} ${c.section} ${c.text}')).toList() {
    _lengths = _docs.map((d) => d.length).toList();
    _avgLen = _lengths.isEmpty
        ? 0.0
        : _lengths.reduce((a, b) => a + b) / _lengths.length;
    _freqs = _docs.map((d) {
      final m = <String, int>{};
      for (final t in d) {
        m[t] = (m[t] ?? 0) + 1;
      }
      return m;
    }).toList();

    final df = <String, int>{};
    for (final d in _docs) {
      for (final t in d.toSet()) {
        df[t] = (df[t] ?? 0) + 1;
      }
    }
    final n = _docs.length;
    _idf = {
      for (final e in df.entries)
        e.key: math.log(1 + (n - e.value + 0.5) / (e.value + 0.5)),
    };
  }

  static const double k1 = 1.5;
  static const double b = 0.75;

  final List<Chunk> chunks;
  final List<List<String>> _docs;
  late final List<int> _lengths;
  late final double _avgLen;
  late final List<Map<String, int>> _freqs;
  late final Map<String, double> _idf;

  List<ScoredChunk> search(
    String query, {
    int k = 5,
    List<String>? classFilter,
  }) {
    final qTerms = tokenize(query);
    final scored = <ScoredChunk>[];
    final filter = classFilter == null || classFilter.isEmpty
        ? null
        : classFilter.toSet();

    for (var i = 0; i < chunks.length; i++) {
      final chunk = chunks[i];
      final chunkClasses = chunk.classes.toSet();
      // A page tagged with classes is only eligible for a matching query;
      // an untagged page (safety, referral) is always eligible.
      if (filter != null &&
          chunkClasses.isNotEmpty &&
          filter.intersection(chunkClasses).isEmpty) {
        continue;
      }
      var score = 0.0;
      final freq = _freqs[i];
      final length = _lengths[i] == 0 ? 1 : _lengths[i];
      for (final term in qTerms) {
        final f = freq[term] ?? 0;
        if (f == 0) continue;
        final idf = _idf[term] ?? 0.0;
        final denom =
            f + k1 * (1 - b + b * length / (_avgLen == 0 ? 1 : _avgLen));
        score += idf * (f * (k1 + 1)) / denom;
      }
      // Boost chunks explicitly tagged with the detected class.
      if (filter != null && filter.intersection(chunkClasses).isNotEmpty) {
        score *= 1.35;
      }
      if (score > 0) scored.add(ScoredChunk(chunk, score, i));
    }
    // Python's list.sort is stable, so equal scores keep corpus order; Dart's
    // is not, and for a 44-chunk corpus with many exact ties that is not a
    // theoretical difference - it reordered real results. Breaking ties on the
    // corpus index reproduces the stable sort exactly.
    scored.sort((a, b) {
      final byScore = b.score.compareTo(a.score);
      return byScore != 0 ? byScore : a.order.compareTo(b.order);
    });
    return scored.length > k ? scored.sublist(0, k) : scored;
  }
}

/// The on-device knowledge base: chunks from one crop pack, plus the retriever
/// over them. Rebuilt when the active pack changes, not per query - the index
/// is a few hundred chunks but it is still pointless work in a hot path.
class KnowledgeBase {
  KnowledgeBase(this.chunks) : retriever = Bm25Retriever(chunks);

  /// Builds from a map of `file name -> markdown source`, sorted by name so
  /// chunk ids are stable across devices (the Python sorts its glob too).
  factory KnowledgeBase.fromDocuments(Map<String, String> docs) {
    final names = docs.keys.toList()..sort();
    final chunks = <Chunk>[];
    for (final name in names) {
      chunks.addAll(chunksForDocument(name, docs[name]!));
    }
    return KnowledgeBase(chunks);
  }

  final List<Chunk> chunks;
  final Bm25Retriever retriever;

  bool get isEmpty => chunks.isEmpty;

  List<Map<String, dynamic>> search(
    String query, {
    int k = 5,
    List<String>? classFilter,
  }) {
    var hits = retriever.search(query, k: k, classFilter: classFilter);
    // Same widening the server does: a class-filtered query that finds nothing
    // is better answered by the general pages than by an empty result.
    if (hits.isEmpty && classFilter != null && classFilter.isNotEmpty) {
      hits = retriever.search(query, k: k);
    }
    return [
      for (final h in hits)
        {
          ...h.chunk.toJson(),
          'text': h.chunk.text,
          'score': double.parse(h.score.toStringAsFixed(4)),
        }
    ];
  }

  /// Everything tagged with a class, in document order - the deterministic
  /// advisory skeleton, which must not depend on what the farmer typed.
  List<Chunk> sectionsForClass(String classKey) =>
      [for (final c in chunks) if (c.classes.contains(classKey)) c];
}
