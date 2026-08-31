"""Integrity checks for the multilingual message catalog.

These exist because a real bug got through: a scripted edit spliced Bengali
text into the wrong catalog entry, and `diag.detected` started returning the
word for "low". Every test still passed, because nothing asserted that a
translation says what it is supposed to say.

A wrong string here is not cosmetic. The catalog carries safety instructions
and referral phone numbers, and a farmer reading a mistranslated advisory has
no way to notice. So the catalog is checked structurally: right script, right
placeholders, no language silently falling back to English.
"""
from __future__ import annotations

import re

import pytest

from app.config import settings
from app.services import taxonomy
from app.services.translate import CATALOG, LANGUAGE_NAMES, coverage, t

# Script ranges. U+0964/U+0965 (danda) sit in the Devanagari block but are
# shared punctuation used by Bengali, Marathi and Hindi alike, so they are
# excluded from the Devanagari range used for leak detection.
BENGALI = re.compile(r"[ঀ-৿]")
DEVANAGARI = re.compile(r"[ऀ-ॣ०-ॿ]")
SCRIPT = {"mr": DEVANAGARI, "hi": DEVANAGARI, "bn": BENGALI}

PLACEHOLDER = re.compile(r"\{(\w+)\}")
LANGS = ("en", "mr", "hi", "bn")


@pytest.mark.parametrize("lang", LANGS)
def test_every_key_is_translated(lang):
    missing = [key for key, entry in CATALOG.items() if not entry.get(lang)]
    assert not missing, f"{lang} is missing {len(missing)} keys: {missing[:5]}"


@pytest.mark.parametrize("lang", ["mr", "hi", "bn"])
def test_translations_use_the_right_script(lang):
    """Catches text spliced into the wrong entry or the wrong language slot."""
    wrong = []
    for key, entry in CATALOG.items():
        value = entry[lang]
        if not SCRIPT[lang].search(value):
            wrong.append((key, "no native script", value))
        if lang == "bn" and DEVANAGARI.search(value):
            wrong.append((key, "Devanagari leaked into Bengali", value))
    assert not wrong, wrong[:5]


@pytest.mark.parametrize("lang", LANGS)
def test_placeholders_survive_translation(lang):
    """A dropped {date} or {disease} renders a literal gap in the advisory."""
    broken = []
    for key, entry in CATALOG.items():
        expected = set(PLACEHOLDER.findall(entry["en"]))
        actual = set(PLACEHOLDER.findall(entry[lang]))
        if expected != actual:
            broken.append((key, lang, sorted(expected), sorted(actual)))
    assert not broken, broken


def test_no_translation_duplicates_a_different_key():
    """The exact failure that occurred: one entry carrying another entry's text.

    Short words legitimately repeat across languages (risk levels, headings),
    so only longer strings are checked -- a duplicated sentence is a real bug.
    """
    for lang in ("mr", "hi", "bn"):
        seen: dict[str, str] = {}
        for key, entry in CATALOG.items():
            value = entry[lang]
            if len(value) < 25:
                continue
            assert value not in seen, (
                f"{lang}: {key!r} and {seen[value]!r} share the same text - "
                "one of them is carrying the wrong translation"
            )
            seen[value] = key


def test_helpline_numbers_appear_in_every_language():
    """Phone numbers must survive translation, in any numeral system."""
    for lang in LANGS:
        text = t("referral.helpline", lang)
        digits = re.sub(r"[^\d०-९০-৯]", "", text)
        assert len(digits) >= 11, f"{lang} helpline lost its number: {text}"


@pytest.mark.parametrize("lang", LANGS)
def test_class_and_threat_names_are_localised(lang):
    for key in taxonomy.CLASS_NAMES:
        name = taxonomy.display_name(key, lang)
        assert name and name != key
        if lang in SCRIPT:
            assert SCRIPT[lang].search(name), f"{key} not localised for {lang}: {name}"
    for key in taxonomy.NON_MODEL_THREATS:
        name = taxonomy.display_name(key, lang)
        assert name and name != key


def test_settings_and_catalog_agree():
    """A language offered in settings but absent from the catalog would fall
    back to English mid-advisory."""
    for lang in settings.languages:
        assert lang in LANGUAGE_NAMES, f"{lang} has no display name"
        assert coverage()[lang]["coverage"] == 1.0


def test_unknown_key_degrades_to_the_key_not_a_crash():
    assert t("does.not.exist", "bn") == "does.not.exist"


def test_unknown_language_falls_back_to_english():
    assert t("heading.safety", "zz") == CATALOG["heading.safety"]["en"]
