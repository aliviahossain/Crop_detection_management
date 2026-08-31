"""Advisory generation: a LangGraph pipeline over the IPDM knowledge base.

    retrieve -> compose -> safety -> localize

Why it is structured rather than a single LLM call: an advisory that names a
pesticide and a dose is a safety-critical output. Every recommendation here is
traceable to a specific knowledge-base section (returned as `citations`), the
dose tables are parsed from that markdown rather than generated, and the
translation layer is template-driven. An LLM, when a key is configured, only
writes the plain-language summary paragraph and translates free text -- it never
invents a dose.

If `langgraph` is not installed the same four nodes run sequentially. The graph
is the real implementation; the fallback exists so a demo machine without the
optional dependency still works.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from app.config import settings
from app.services import taxonomy
from app.services.knowledge_base import knowledge_base
from app.services.translate import normalise_language, t, translate_free_text

log = logging.getLogger(__name__)

FOLLOW_UP_DAYS = {
    "potato_late_blight": 5,
    "potato_early_blight": 7,
    "potato_healthy": 7,
    "potato_tuber_moth": 7,
    "aphid_vector": 7,
}
DEFAULT_FOLLOW_UP_DAYS = 7

# Which template actions apply to which situation.
IMMEDIATE_ACTIONS: dict[str, list[str]] = {
    "potato_late_blight": [
        "action.remove_infected",
        "action.stop_evening_irrigation",
        "action.earthing_up",
        "action.rotate_chemistry",
    ],
    "potato_early_blight": [
        "action.remove_infected",
        "action.scout",
        "action.rotate_chemistry",
    ],
    "potato_healthy": ["action.no_spray", "action.scout", "action.earthing_up"],
    "potato_tuber_moth": ["action.check_traps", "action.earthing_up"],
    "aphid_vector": ["action.scout"],
}
SAFETY_BULLETS = [
    "safety.licensed_dealer",
    "safety.label_dose",
    "safety.ppe",
    "safety.wind",
    "safety.phi",
    "safety.container",
    "safety.children",
    "safety.poison_helpline",
]


class AdvisoryState(TypedDict, total=False):
    # inputs
    class_key: str | None
    confidence: float | None
    model_available: bool
    has_detection: bool
    risk: dict | None
    triage: dict | None
    language: str
    query: str
    # intermediate / outputs
    citations: list[dict]
    kb_hits: list[dict]
    advisory: dict


# ----------------------------------------------------------------------
# Markdown table -> structured chemical options
# ----------------------------------------------------------------------
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")


def parse_dose_table(text: str) -> list[dict]:
    """Pull `| Product | Dose | Notes |` rows out of a KB section.

    Parsing the doses out of reviewed markdown -- rather than having a model
    write them -- is what keeps the numbers accountable to a human-edited
    source file.
    """
    rows: list[dict] = []
    header: list[str] | None = None
    for line in text.splitlines():
        m = _TABLE_ROW.match(line.strip())
        if not m:
            header = None
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if all(set(c) <= {"-", ":", " "} and c for c in cells):
            continue  # separator row
        if header is None:
            header = [c.lower() for c in cells]
            continue
        row = dict(zip(header, cells))
        if row.get("product"):
            rows.append(
                {
                    "product": row.get("product", ""),
                    "dose": row.get("dose", ""),
                    "notes": row.get("notes", ""),
                }
            )
    return rows


# ----------------------------------------------------------------------
# Graph nodes
# ----------------------------------------------------------------------
def node_retrieve(state: AdvisoryState) -> AdvisoryState:
    class_key = state.get("class_key")
    risk = state.get("risk") or {}
    parts = [
        taxonomy.display_name(class_key) if class_key else "",
        "management treatment dose spray control",
    ]
    if risk.get("overall_level") in {"medium", "high"}:
        parts.append(f"preventive {risk.get('top_threat', '')}")
    query = state.get("query") or " ".join(p for p in parts if p)

    class_filter = [c for c in [class_key, risk.get("top_threat")] if c]
    hits = knowledge_base.search(query, k=6, class_filter=class_filter or None)
    return {**state, "query": query, "kb_hits": hits}


def _summary_paragraph(state: AdvisoryState, lang: str) -> tuple[str, bool]:
    """Plain-language opening line. LLM-written when available, template
    otherwise. Nothing safety-critical lives here."""
    class_key = state.get("class_key")
    conf = state.get("confidence")
    risk = state.get("risk") or {}
    triage = state.get("triage") or {}

    if not state.get("model_available", True):
        base = t("diag.unavailable", lang)
    elif not state.get("has_detection", True):
        # Proactive path: /risk with no image. Never phrase a forecast as a
        # diagnosis -- a farmer acting on "detected" would be acting on nothing.
        base = t("diag.forecast_only", lang)
    elif class_key == "potato_healthy":
        base = t("diag.healthy", lang)
    elif class_key:
        base = t(
            "diag.detected",
            lang,
            disease=taxonomy.display_name(class_key, lang),
            confidence=f"{(conf or 0):.0%}",
        )
    else:
        base = t("diag.uncertain", lang)

    if not triage.get("self_treatment_allowed", True):
        base = f"{base} {t('diag.uncertain', lang)}"

    if risk.get("threats"):
        top = risk["threats"][0]
        base = f"{base} " + t(
            "risk.sentence",
            lang,
            threat=taxonomy.display_name(top["key"], lang),
            level=t(f"risk.{top['level']}", lang),
        )
        smith = next(
            (
                m
                for th in risk["threats"]
                for m in th.get("models", [])
                if m.get("name") == "smith_period" and m.get("triggered")
            ),
            None,
        )
        if smith:
            base = f"{base} {t('risk.smith_fired', lang)}"
    return base, False


def node_compose(state: AdvisoryState) -> AdvisoryState:
    lang = state.get("language", "en")
    class_key = state.get("class_key")
    risk = state.get("risk") or {}
    triage = state.get("triage") or {}
    hits = state.get("kb_hits", [])

    summary, _ = _summary_paragraph(state, lang)

    # Immediate actions
    action_keys = list(IMMEDIATE_ACTIONS.get(class_key or "", []))
    if class_key == "potato_healthy" and risk.get("overall_level") == "high":
        action_keys = ["action.protectant", "action.scout", "action.stop_evening_irrigation"]
    if not action_keys:
        action_keys = ["action.scout"]
    immediate = [t(k, lang) for k in action_keys]

    # Chemical options: only when a chemical response is actually justified.
    chemical_options: list[dict] = []
    chemical_gate: str
    actionable = taxonomy.is_actionable(class_key)
    risk_high = risk.get("overall_level") == "high"
    if not triage.get("self_treatment_allowed", True):
        chemical_gate = "withheld_pending_expert_confirmation"
    elif actionable or risk_high:
        target = class_key if actionable else risk.get("top_threat")
        # Collect every dose table in the target's knowledge-base document.
        # Matching on the table structure rather than on section titles means
        # renaming a heading (or adding a "Curative / systemic" block) cannot
        # silently drop half the treatment options from a farmer's advisory.
        for section in knowledge_base.sections_for_class(target or ""):
            chemical_options.extend(parse_dose_table(section["text"]))
        # No dose table is not a data gap -- for tuber moth and aphids the
        # knowledge base deliberately recommends monitoring, cultural control
        # and an officer consultation instead of a routine spray.
        chemical_gate = "recommended" if chemical_options else "non_chemical_first"
    else:
        chemical_gate = "not_required"

    # Cultural / preventive practice, taken verbatim from the reviewed KB.
    cultural: list[str] = []
    for section in knowledge_base.sections_for_class(class_key or ""):
        title = section["section"].lower()
        if "cultural" in title or "preventive" in title or "keep it healthy" in title:
            cultural.extend(
                re.sub(r"^[-*]\s*", "", line).strip()
                for line in section["text"].splitlines()
                if line.strip().startswith(("-", "*"))
            )

    follow_up_days = FOLLOW_UP_DAYS.get(class_key or "", DEFAULT_FOLLOW_UP_DAYS)
    follow_up_date = (datetime.now(timezone.utc) + timedelta(days=follow_up_days)).date()

    advisory = {
        "language": lang,
        "summary": summary,
        "sections": [
            {"key": "immediate", "heading": t("heading.immediate", lang), "items": immediate},
            {
                "key": "cultural",
                "heading": t("heading.cultural", lang),
                "items": cultural[:8],
            },
        ],
        "chemical": {
            "heading": t("heading.chemical", lang),
            "status": chemical_gate,
            "status_note": {
                "withheld_pending_expert_confirmation": t("chemical.withheld", lang),
                "not_required": t("chemical.not_required", lang),
                "non_chemical_first": t("chemical.non_chemical_first", lang),
            }.get(chemical_gate),
            "options": chemical_options,
            "disclaimer": t("note.verify_local", lang),
            "rotation_note": t("action.rotate_chemistry", lang),
        },
        "follow_up": {
            "heading": t("heading.followup", lang),
            "days": follow_up_days,
            "date": follow_up_date.isoformat(),
            "text": t("followup.scheduled", lang, date=follow_up_date.isoformat()),
            "why": t("followup.why", lang),
        },
        "references": [
            {
                "title": h["title"],
                "section": h["section"],
                "doc_id": h["doc_id"],
                "score": h["score"],
                "excerpt": h["text"][:600],
                "sources": h.get("sources", []),
            }
            for h in hits[:4]
        ],
    }
    return {**state, "advisory": advisory, "citations": advisory["references"]}


def node_safety(state: AdvisoryState) -> AdvisoryState:
    """Attach safe-use rules and the referral instruction. Runs after compose so
    it can never be skipped by the composition logic."""
    lang = state.get("language", "en")
    advisory = dict(state.get("advisory") or {})
    triage = state.get("triage") or {}

    advisory["safety"] = {
        "heading": t("heading.safety", lang),
        "items": [t(k, lang) for k in SAFETY_BULLETS],
        "applies": advisory.get("chemical", {}).get("status") == "recommended",
    }

    referral_level = triage.get("referral_level")
    referral_items: list[str] = []
    if triage.get("escalate"):
        referral_items.append(t(f"referral.{referral_level or 'village'}", lang))
    referral_items.append(t("referral.helpline", lang))
    advisory["referral"] = {
        "heading": t("heading.referral", lang),
        "required": bool(triage.get("escalate")),
        "level": referral_level,
        "urgency": t(f"urgency.{triage.get('urgency', 'routine')}", lang),
        "items": referral_items,
        "reasons": triage.get("reasons", []),
    }
    return {**state, "advisory": advisory}


def node_localize(state: AdvisoryState) -> AdvisoryState:
    """Templates are already localized. This node handles the free-text KB
    excerpts, which only an LLM can translate."""
    lang = state.get("language", "en")
    advisory = dict(state.get("advisory") or {})
    if lang == "en":
        advisory["translation"] = {"mode": "source", "excerpts_translated": False}
        return {**state, "advisory": advisory}

    translated_any = False
    if settings.llm_enabled:
        for ref in advisory.get("references", []):
            text, ok = translate_free_text(ref["excerpt"], lang)
            if ok:
                ref["excerpt_translated"] = text
                translated_any = True
    advisory["translation"] = {
        "mode": "template+llm" if translated_any else "template",
        "excerpts_translated": translated_any,
        "note": None if translated_any else t("note.english_excerpt", lang),
    }
    return {**state, "advisory": advisory}


# ----------------------------------------------------------------------
# Graph assembly
# ----------------------------------------------------------------------
_graph = None
_graph_backend = "sequential"


def _build_graph():
    global _graph, _graph_backend
    if _graph is not None:
        return _graph
    try:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(AdvisoryState)
        builder.add_node("retrieve", node_retrieve)
        builder.add_node("compose", node_compose)
        builder.add_node("safety", node_safety)
        builder.add_node("localize", node_localize)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "compose")
        builder.add_edge("compose", "safety")
        builder.add_edge("safety", "localize")
        builder.add_edge("localize", END)
        _graph = builder.compile()
        _graph_backend = "langgraph"
        log.info("Advisory pipeline compiled with LangGraph")
    except Exception as exc:
        log.warning("LangGraph unavailable (%s); running nodes sequentially", exc)
        _graph = None
        _graph_backend = "sequential"
    return _graph


def pipeline_status() -> dict:
    _build_graph()
    return {
        "backend": _graph_backend,
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.advisory_llm_model if settings.llm_enabled else None,
        "knowledge_base": knowledge_base.status(),
    }


def generate(
    *,
    class_key: str | None,
    confidence: float | None = None,
    model_available: bool = True,
    has_detection: bool = True,
    risk: dict | None = None,
    triage: dict | None = None,
    language: str = "en",
    query: str | None = None,
) -> dict[str, Any]:
    state: AdvisoryState = {
        "class_key": class_key,
        "confidence": confidence,
        "model_available": model_available,
        "has_detection": has_detection,
        "risk": risk,
        "triage": triage,
        "language": normalise_language(language),
        "query": query or "",
    }
    graph = _build_graph()
    if graph is not None:
        result = graph.invoke(state)
    else:
        result = state
        for node in (node_retrieve, node_compose, node_safety, node_localize):
            result = node(result)
    advisory = dict(result.get("advisory") or {})
    advisory["pipeline"] = _graph_backend
    return advisory
