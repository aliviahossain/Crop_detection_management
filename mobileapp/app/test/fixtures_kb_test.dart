/// Holds the on-device BM25 retriever to the Python service's scores.
///
/// The handset has no vector backend, so this lexical path IS on-device
/// retrieval - not a fallback that only runs when something else breaks. If it
/// drifts, a farmer and an officer asking the same question get different dose
/// tables, and nothing in either app would look wrong.
///
/// Regenerate with:  python mobileapp/tools/export_fixtures.py --write
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:cropguard/kb/knowledge_base.dart';

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

/// The same corpus the fixture generator indexed: the repo's KB pages, which
/// are also what `build_pack.py` copies into a crop pack.
Map<String, String> _loadCorpus() {
  final dir = Directory('../../backend/app/data/kb');
  if (!dir.existsSync()) {
    throw StateError('Missing ${dir.absolute.path}');
  }
  final docs = <String, String>{};
  for (final f in dir.listSync().whereType<File>()) {
    if (!f.path.endsWith('.md')) continue;
    docs[f.uri.pathSegments.last] = f.readAsStringSync();
  }
  return docs;
}

void main() {
  final suite = _loadSuite('kb');
  final cases = (suite['cases'] as List).cast<Map<String, dynamic>>();
  final kb = KnowledgeBase.fromDocuments(_loadCorpus());

  test('fixture suite is present and non-trivial', () {
    expect(suite['source'], 'backend/app/services/knowledge_base.py');
    expect(cases.length, greaterThanOrEqualTo(20));
  });

  test('the corpus chunks identically to the Python loader', () {
    // Chunk ids encode document order and section index, so this single
    // assertion catches a front-matter parse that swallows a heading, an
    // off-by-one in section splitting, and a differently sorted file list.
    final corpus = suite['corpus'] as Map<String, dynamic>;
    expect(kb.chunks.length, corpus['chunk_count']);
    expect(
      kb.chunks.map((c) => c.chunkId).toList(),
      (corpus['chunk_ids'] as List).cast<String>(),
    );
  });

  group('tokenize', () {
    for (final c in cases.where((c) => c['fn'] == 'tokenize')) {
      test('${c['id']} - ${c['why']}', () {
        final input = c['input'] as Map<String, dynamic>;
        final expected = (c['expect'] as Map)['tokens'] as List;
        expect(tokenize(input['text'] as String), expected.cast<String>());
      });
    }
  });

  group('load_chunks', () {
    for (final c in cases.where((c) => c['fn'] == 'load_chunks')) {
      test('${c['id']} - ${c['why']}', () {
        final input = c['input'] as Map<String, dynamic>;
        final expected = c['expect'] as Map<String, dynamic>;
        final doc = input['doc'] as String;
        final docId = doc.replaceAll('.md', '');
        final got = kb.chunks.where((ch) => ch.docId == docId).toList();

        expect(got.length, expected['chunk_count']);
        expect(got.map((ch) => ch.chunkId).toList(),
            (expected['chunk_ids'] as List).cast<String>());
        expect(got.map((ch) => ch.section).toList(),
            (expected['sections'] as List).cast<String>());
        if (got.isNotEmpty) {
          expect(got.first.title, expected['title']);
          expect(got.first.classes, (expected['classes'] as List).cast<String>());
          expect(got.first.kind, expected['kind']);
          expect(got.first.sources, (expected['sources'] as List).cast<String>());
        }
      });
    }
  });

  group('BM25 search', () {
    for (final c in cases.where((c) => c['fn'] == 'search')) {
      test('${c['id']} - ${c['why']}', () {
        final input = c['input'] as Map<String, dynamic>;
        final expected = c['expect'] as Map<String, dynamic>;
        final filter = (input['class_filter'] as List?)?.cast<String>();

        // The fixture calls BM25Retriever.search directly, so this must too:
        // the widen-on-empty behaviour lives one layer up in KnowledgeBase and
        // is asserted separately below.
        final hits = kb.retriever.search(
          input['query'] as String,
          k: (input['k'] as num).toInt(),
          classFilter: filter,
        );

        expect(hits.map((h) => h.chunk.chunkId).toList(),
            (expected['chunk_ids'] as List).cast<String>(),
            reason: 'ranking order differs from the Python retriever');

        final wantScores = (expected['scores'] as List).cast<num>();
        expect(hits.length, wantScores.length);
        for (var i = 0; i < hits.length; i++) {
          expect(hits[i].score, closeTo(wantScores[i].toDouble(), 1e-4),
              reason: 'score ${i + 1} (${hits[i].chunk.chunkId})');
        }
      });
    }
  });

  group('KnowledgeBase wrapper', () {
    test('widens to an unfiltered search when a class filter finds nothing',
        () {
      // Mirrors the server: an unknown class should fall back to the general
      // pages rather than leaving the farmer with no advice at all.
      final narrow =
          kb.retriever.search('late blight', classFilter: ['tomato_leaf_curl']);
      expect(narrow, isEmpty);
      final widened =
          kb.search('late blight', classFilter: ['tomato_leaf_curl']);
      expect(widened, isNotEmpty);
    });

    test('sectionsForClass returns tagged chunks in document order', () {
      final got = kb.sectionsForClass('potato_late_blight');
      expect(got, isNotEmpty);
      expect(got.every((c) => c.classes.contains('potato_late_blight')), isTrue);
      final ids = got.map((c) => c.chunkId).toList();
      final sorted = [...ids]..sort(
          (a, b) => kb.chunks.indexWhere((c) => c.chunkId == a).compareTo(
              kb.chunks.indexWhere((c) => c.chunkId == b)));
      expect(ids, sorted);
    });
  });
}
