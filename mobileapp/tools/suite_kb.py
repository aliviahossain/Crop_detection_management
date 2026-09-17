"""Golden vectors for `backend/app/services/knowledge_base.py` (BM25 half).

The phone has no ChromaDB, so on-device retrieval is the BM25 path. That makes
the lexical scorer load-bearing rather than a fallback, and it has to agree
with the server: the same query typed by a farmer on a handset and by an
officer at a desk should surface the same dose table, in the same order.

Three things in this port are easy to get subtly wrong, so all three are
pinned here rather than eyeballed:

* **The tokenizer.** `[a-z0-9][a-z0-9\\-\\.]*` keeps `2.5`, `mancozeb-75` and
  `0.2%` whole. A naive `\\w+` split would shred exactly the dose strings the
  retrieval exists to find, and would still look fine on prose queries.
* **The stopword and length filter.** Dropping tokens of length <= 1 after
  stopword removal changes document lengths, which changes every BM25 score
  through the length-normalisation term - not just the scores of queries
  containing stopwords.
* **The class boost.** A 1.35x multiplier applied after scoring, and only to
  chunks tagged with the filtered class. Applying it before, or to untagged
  chunks, reorders results in a way that reads as plausible either way.

Scores are rounded to 4 decimal places, matching what the service returns.
"""
from __future__ import annotations

from pathlib import Path

from app.services.knowledge_base import BM25Retriever, load_chunks, tokenize

SOURCE = "backend/app/services/knowledge_base.py"

REPO = Path(__file__).resolve().parents[2]
KB_DIR = REPO / "backend" / "app" / "data" / "kb"

# (name, why, text)
TOKENIZE_CASES = [
    ("plain_prose", "Baseline: lowercasing and stopword removal.", "The white downy growth on the underside of a leaf"),
    ("dose_decimal", "A decimal dose must survive as one token, not split at the point.", "Apply mancozeb 2.5 g/litre of water"),
    ("percentage", "Percent strings are how labels express concentration.", "Mancozeb 75% WP at 0.2%"),
    ("hyphenated", "Hyphens join product names and must not split them.", "metalaxyl-m + mancozeb-75 ws"),
    ("single_chars", "Single characters are dropped AFTER stopwords, changing doc length.", "a b c 1 2 potato"),
    ("mixed_case_units", "Units and case: kg/ha, ML, pH.", "Use 2 kg/ha at pH 6.5 in 500 ML water"),
    ("all_stopwords", "A query of nothing but stopwords must tokenize to empty.", "the a an and or of to in is are"),
    ("empty", "Empty input, empty token list - not a crash.", ""),
    ("punctuation_only", "Punctuation yields nothing; the regex needs a leading alnum.", "--- ... ***"),
    ("devanagari", "Non-latin script is out of the regex class entirely.", "बटाटा करपा"),
]

# (name, why, query, k, class_filter)
SEARCH_CASES = [
    ("late_blight_by_class", "The core path: a detected class drives retrieval.",
     "late blight treatment", 5, ["potato_late_blight"]),
    ("late_blight_no_filter", "Same query unfiltered - proves the 1.35x boost actually reorders.",
     "late blight treatment", 5, None),
    ("early_blight_by_class", "Second disease, to catch a port that hardcodes the first.",
     "early blight concentric rings", 5, ["potato_early_blight"]),
    ("dose_query", "A dose lookup, where the tokenizer decides whether it works at all.",
     "mancozeb dose per litre", 5, None),
    ("safety_query", "Safety pages carry no class tag and must stay eligible under a filter.",
     "protective equipment spraying safety", 5, ["potato_late_blight"]),
    ("referral_query", "The escalation page, retrieved by intent rather than class.",
     "when to call an extension officer", 3, None),
    ("healthy_query", "Healthy is a class too, and its page is mostly preventive advice.",
     "preventive spray healthy crop", 5, ["potato_healthy"]),
    ("pest_query", "Pests live on their own page with their own class tags.",
     "tuber moth trap", 5, None),
    ("unmatched_filter", "A class nothing is tagged with must widen to an unfiltered search.",
     "late blight", 5, ["tomato_leaf_curl"]),
    ("no_hits_at_all", "A query with no lexical overlap returns empty, not an error.",
     "zzzz qqqq xxxx", 5, None),
    ("k_is_one", "Top-1 only - pins which chunk actually wins, not just the set.",
     "white downy growth underside leaf", 1, ["potato_late_blight"]),
    ("k_larger_than_corpus", "k beyond the number of scoring chunks must not pad or crash.",
     "potato", 100, None),
]

# (name, why, doc) - parsing, which decides what BM25 even sees
DOC_CASES = [
    ("late_blight", "Front matter with a block list of sources and a class tag.", "potato_late_blight.md"),
    ("safe_input_usage", "A cross-cutting page with no class tag.", "safe_input_usage.md"),
    ("healthy", "Shortest page - guards off-by-one in section splitting.", "potato_healthy.md"),
]


def build() -> dict:
    cases = []

    for name, why, text in TOKENIZE_CASES:
        cases.append({
            "id": name,
            "why": why,
            "fn": "tokenize",
            "input": {"text": text},
            "expect": {"tokens": tokenize(text)},
        })

    chunks = load_chunks(KB_DIR)

    for name, why, doc in DOC_CASES:
        doc_chunks = [c for c in chunks if c.doc_id == doc.replace(".md", "")]
        cases.append({
            "id": name,
            "why": why,
            "fn": "load_chunks",
            "input": {"doc": doc},
            "expect": {
                "chunk_count": len(doc_chunks),
                "chunk_ids": [c.chunk_id for c in doc_chunks],
                "sections": [c.section for c in doc_chunks],
                "title": doc_chunks[0].title if doc_chunks else None,
                "classes": doc_chunks[0].classes if doc_chunks else [],
                "kind": doc_chunks[0].kind if doc_chunks else "",
                "sources": doc_chunks[0].sources if doc_chunks else [],
            },
        })

    # The corpus the retriever indexes is every page, exactly as the app will
    # index every page in the installed pack.
    retriever = BM25Retriever(chunks)

    for name, why, query, k, class_filter in SEARCH_CASES:
        hits = retriever.search(query, k=k, class_filter=class_filter)
        cases.append({
            "id": name,
            "why": why,
            "fn": "search",
            "input": {"query": query, "k": k, "class_filter": class_filter},
            "expect": {
                "chunk_ids": [c.chunk_id for c, _ in hits],
                "scores": [round(float(s), 4) for _, s in hits],
            },
        })

    return {
        "suite": "kb",
        "source": SOURCE,
        "description": (
            "Tokenizer, markdown chunking and BM25 ranking for the on-device "
            "knowledge base. The phone has no vector backend, so these ARE the "
            "retrieval semantics, not a fallback."
        ),
        "corpus": {
            "doc_count": len({c.doc_id for c in chunks}),
            "chunk_count": len(chunks),
            # Pinned so a KB edit that changes retrieval shows up as a fixture
            # diff rather than as a quietly different answer in the field.
            "chunk_ids": [c.chunk_id for c in chunks],
        },
        "cases": cases,
    }
