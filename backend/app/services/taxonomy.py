"""The classes the deployed detector actually knows.

Scope decision: the trained model covers POTATO ONLY, with three classes.
Potato is the right first crop for this PS -- late blight is the textbook
weather-driven epidemic (the Smith Period is defined for it), it is a major
Maharashtra rabi crop, and PlantVillage has clean potato imagery. Adding crops
is a data + retrain job, not a code change: extend CLASSES and the KB.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CROP = "potato"


@dataclass(frozen=True)
class ClassInfo:
    key: str                    # model label, must match ml/data.yaml order
    display: str
    crop: str
    kind: str                   # disease | pest | healthy
    pathogen: str | None
    severity: str               # none | moderate | high
    kb_doc: str                 # file in backend/app/data/kb
    names: dict[str, str] = field(default_factory=dict)  # localized display


CLASSES: list[ClassInfo] = [
    ClassInfo(
        key="potato_early_blight",
        display="Potato — Early Blight",
        crop=CROP,
        kind="disease",
        pathogen="Alternaria solani",
        severity="moderate",
        kb_doc="potato_early_blight.md",
        names={
            "mr": "बटाटा — लवकर येणारा करपा",
            "hi": "आलू — अगेती झुलसा",
            "bn": "আলু — আগাম ধসা",
        },
    ),
    ClassInfo(
        key="potato_late_blight",
        display="Potato — Late Blight",
        crop=CROP,
        kind="disease",
        pathogen="Phytophthora infestans",
        severity="high",
        kb_doc="potato_late_blight.md",
        names={
            "mr": "बटाटा — उशिरा येणारा करपा",
            "hi": "आलू — पछेती झुलसा",
            "bn": "আলু — নাবি ধসা",
        },
    ),
    ClassInfo(
        key="potato_healthy",
        display="Potato — Healthy",
        crop=CROP,
        kind="healthy",
        pathogen=None,
        severity="none",
        kb_doc="potato_healthy.md",
        names={
            "mr": "बटाटा — निरोगी",
            "hi": "आलू — स्वस्थ",
            "bn": "আলু — সুস্থ",
        },
    ),
]

# Index order IS the model's class index order. Keep in lockstep with ml/data.yaml.
CLASS_NAMES: list[str] = [c.key for c in CLASSES]
BY_KEY: dict[str, ClassInfo] = {c.key: c for c in CLASSES}


# Threats the *risk engine* forecasts but the image model does not detect (no
# training imagery for them). Kept out of CLASSES so they can never be returned
# as a detection, but named here so advisories can address them in-language.
NON_MODEL_THREATS: dict[str, dict[str, str]] = {
    "potato_tuber_moth": {
        "en": "Potato tuber moth",
        "mr": "बटाटा पोखरणारी अळी",
        "hi": "आलू कंद कीट",
        "bn": "আলুর মথ পোকা",
    },
    "aphid_vector": {
        "en": "Aphid complex (virus vectors)",
        "mr": "मावा किडी (विषाणू वाहक)",
        "hi": "माहू कीट (विषाणु वाहक)",
        "bn": "জাব পোকা (ভাইরাস বাহক)",
    },
}


def get(key: str | None) -> ClassInfo | None:
    return BY_KEY.get(key) if key else None


def display_name(key: str | None, lang: str = "en") -> str:
    """Localized name for anything the system can name: a model class or a
    forecast-only threat."""
    info = get(key)
    if info is not None:
        return info.names.get(lang, info.display)
    if key in NON_MODEL_THREATS:
        names = NON_MODEL_THREATS[key]
        return names.get(lang, names["en"])
    return key or "unknown"


def is_actionable(key: str | None) -> bool:
    """Healthy / unknown does not warrant a pesticide recommendation."""
    info = get(key)
    return bool(info and info.kind in {"disease", "pest"})
