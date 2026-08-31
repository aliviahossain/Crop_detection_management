"""IPDM knowledge base: parsing, chunking and retrieval.

The corpus lives in `backend/app/data/kb/*.md` as human-editable markdown with
YAML front matter. An extension officer or agronomist can review and correct it
in a pull request without touching code -- which matters, because the brief is
right that sourcing accurate treatment and dosage guidance is real content work,
not a config step.

Two retrieval backends:

* **chroma** -- ChromaDB vector search, the stack default.
* **lexical** -- a dependency-free BM25 implementation.

Backend selection is `auto` by default: try Chroma, fall back to BM25 if it is
not installed or cannot download its embedding model. The fallback exists
because the target dev machine is disk-constrained and because a demo must not
die when a model download fails. Retrieval quality is reported in the API
response either way.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

BACKEND_PREFERENCE = os.getenv("ADVISORY_BACKEND", "auto").lower()  # auto | chroma | lexical
COLLECTION_NAME = "ipdm_kb"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\.]*")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "for", "on",
    "with", "as", "at", "by", "it", "this", "that", "be", "from", "not", "no",
    "do", "does", "can", "if", "then", "than", "so", "we", "you", "your",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    title: str
    section: str
    text: str
    classes: list[str] = field(default_factory=list)
    kind: str = ""
    crop: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "section": self.section,
            "classes": self.classes,
            "kind": self.kind,
            "sources": self.sources,
        }


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------
def _parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    meta_raw, body = parts[1], parts[2]
    try:
        import yaml

        meta = yaml.safe_load(meta_raw) or {}
    except Exception:  # pragma: no cover - yaml always present via chromadb
        meta = _minimal_yaml(meta_raw)
    return meta if isinstance(meta, dict) else {}, body


def _minimal_yaml(raw: str) -> dict:
    """Enough YAML for our front matter, so the KB loads even without PyYAML."""
    out: dict = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_list_key:
            out.setdefault(current_list_key, []).append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            current_list_key = key
            out[key] = []
        elif value.startswith("[") and value.endswith("]"):
            out[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            current_list_key = None
        else:
            out[key] = value
            current_list_key = None
    return out


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Chunk on markdown headings. Sections are the natural retrieval unit --
    'Chemical management' should come back whole, table and all."""
    sections: list[tuple[str, str]] = []
    current_title = "Overview"
    buffer: list[str] = []
    for line in body.splitlines():
        if re.match(r"^#{1,3} ", line):
            if any(l.strip() for l in buffer):
                sections.append((current_title, "\n".join(buffer).strip()))
            current_title = line.lstrip("#").strip()
            buffer = []
        else:
            buffer.append(line)
    if any(l.strip() for l in buffer):
        sections.append((current_title, "\n".join(buffer).strip()))
    return sections


def load_chunks(kb_dir: Path | None = None) -> list[Chunk]:
    kb_dir = Path(kb_dir or settings.kb_dir)
    chunks: list[Chunk] = []
    for path in sorted(kb_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        doc_id = str(meta.get("id") or path.stem)
        title = str(meta.get("title") or path.stem)
        classes = meta.get("classes") or []
        if isinstance(classes, str):
            classes = [classes]
        sources = meta.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        for idx, (section, text) in enumerate(_split_sections(body)):
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}#{idx}",
                    title=title,
                    section=section,
                    text=text,
                    classes=[str(c) for c in classes],
                    kind=str(meta.get("kind", "")),
                    crop=str(meta.get("crop", "")),
                    sources=[str(s) for s in sources],
                )
            )
    return chunks


# ----------------------------------------------------------------------
# Lexical (BM25) retriever - the dependency-free fallback
# ----------------------------------------------------------------------
class BM25Retriever:
    K1 = 1.5
    B = 0.75

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.docs = [tokenize(f"{c.title} {c.section} {c.text}") for c in chunks]
        self.lengths = [len(d) for d in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.freqs = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {
            term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()
        }

    def search(self, query: str, k: int = 5, class_filter: list[str] | None = None) -> list[tuple[Chunk, float]]:
        q_terms = tokenize(query)
        scored: list[tuple[Chunk, float]] = []
        for i, chunk in enumerate(self.chunks):
            if class_filter and chunk.classes and not set(class_filter) & set(chunk.classes):
                continue
            score = 0.0
            freq = self.freqs[i]
            length = self.lengths[i] or 1
            for term in q_terms:
                f = freq.get(term, 0)
                if not f:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = f + self.K1 * (1 - self.B + self.B * length / (self.avg_len or 1))
                score += idf * (f * (self.K1 + 1)) / denom
            # Boost chunks explicitly tagged with the detected class.
            if class_filter and set(class_filter) & set(chunk.classes):
                score *= 1.35
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:k]


# ----------------------------------------------------------------------
# Chroma retriever
# ----------------------------------------------------------------------
class ChromaRetriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        import chromadb

        self.chunks_by_id = {c.chunk_id: c for c in chunks}
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
        existing = set(self.collection.get(include=[]).get("ids", []))
        missing = [c for c in chunks if c.chunk_id not in existing]
        if missing:
            self.collection.upsert(
                ids=[c.chunk_id for c in missing],
                documents=[f"{c.title} - {c.section}\n{c.text}" for c in missing],
                metadatas=[
                    {
                        "doc_id": c.doc_id,
                        "title": c.title,
                        "section": c.section,
                        "classes": ",".join(c.classes),
                        "kind": c.kind,
                    }
                    for c in missing
                ],
            )
            log.info("Indexed %d KB chunks into ChromaDB", len(missing))

    def search(self, query: str, k: int = 5, class_filter: list[str] | None = None) -> list[tuple[Chunk, float]]:
        res = self.collection.query(query_texts=[query], n_results=max(k * 3, k))
        out: list[tuple[Chunk, float]] = []
        for cid, dist in zip(res.get("ids", [[]])[0], res.get("distances", [[]])[0]):
            chunk = self.chunks_by_id.get(cid)
            if chunk is None:
                continue
            if class_filter and chunk.classes and not set(class_filter) & set(chunk.classes):
                continue
            score = 1.0 - float(dist)  # cosine distance -> similarity
            if class_filter and set(class_filter) & set(chunk.classes):
                score *= 1.35
            out.append((chunk, score))
        out.sort(key=lambda kv: kv[1], reverse=True)
        return out[:k]


# ----------------------------------------------------------------------
# Facade
# ----------------------------------------------------------------------
class KnowledgeBase:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False
        self._chunks: list[Chunk] = []
        self._retriever = None
        self._backend = "uninitialised"
        self._note: str | None = None

    def _build(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self._chunks = load_chunks()
            if BACKEND_PREFERENCE in {"auto", "chroma"}:
                try:
                    self._retriever = ChromaRetriever(self._chunks)
                    self._backend = "chroma"
                except Exception as exc:
                    if BACKEND_PREFERENCE == "chroma":
                        raise
                    self._note = (
                        f"ChromaDB unavailable ({type(exc).__name__}: {exc}); "
                        "using the built-in BM25 retriever."
                    )
                    log.warning(self._note)
            if self._retriever is None:
                self._retriever = BM25Retriever(self._chunks)
                self._backend = "lexical-bm25"
            self._ready = True

    def reindex(self) -> dict:
        with self._lock:
            self._ready = False
            self._retriever = None
        self._build()
        return self.status()

    def status(self) -> dict:
        self._build()
        return {
            "backend": self._backend,
            "chunks": len(self._chunks),
            "documents": len({c.doc_id for c in self._chunks}),
            "kb_dir": str(settings.kb_dir),
            "note": self._note,
        }

    def search(self, query: str, k: int = 5, class_filter: list[str] | None = None) -> list[dict]:
        self._build()
        hits = self._retriever.search(query, k=k, class_filter=class_filter)
        if not hits and class_filter:
            hits = self._retriever.search(query, k=k, class_filter=None)
        return [
            {**chunk.to_dict(), "text": chunk.text, "score": round(float(score), 4)}
            for chunk, score in hits
        ]

    def sections_for_class(self, class_key: str) -> list[dict]:
        """Everything tagged with a class, in document order -- used to build
        the deterministic advisory skeleton."""
        self._build()
        return [
            {**c.to_dict(), "text": c.text}
            for c in self._chunks
            if class_key in c.classes
        ]


knowledge_base = KnowledgeBase()
