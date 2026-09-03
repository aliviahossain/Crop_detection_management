"""Assistant chatbot backed by Google Gemini.

The Gemini API key lives here, on the server, and never reaches the browser --
the frontend only ever talks to our own ``POST /chat``. When no key is set the
service answers from a small canned fallback so the floating assistant is still
useful on a fresh install (same "documented fallback" philosophy as the weather
and advisory layers).
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("cropguard.chat")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Keep the model on topic and grounded in what this app actually does.
SYSTEM_PROMPT = (
    "You are CropGuard's assistant, a friendly helper inside a potato crop "
    "disease-detection app used by farmers and agriculture officers in "
    "Maharashtra, India. The app can: diagnose potato disease from a leaf photo "
    "(early blight, late blight, healthy), run a live camera scan, forecast "
    "weather-driven disease risk, show a hotspot map, and route uncertain cases "
    "to an expert review queue. Answer questions about potato diseases, safe "
    "pesticide/fungicide (IPDM) practice, and how to use the app. Be concise and "
    "practical -- a few short sentences or a short list. If a diagnosis is "
    "uncertain or the situation looks severe, tell the user to use the photo "
    "check and consult a local agriculture officer. Never invent specific "
    "chemical doses; point users to the app's advisory for exact products and "
    "doses. Reply in the language named by the user's language code."
)

_LANG_NAME = {"en": "English", "mr": "Marathi", "hi": "Hindi", "bn": "Bengali"}

# Offline replies, one per supported UI language, shown when no Gemini key is set.
_FALLBACK = {
    "en": (
        "The live assistant is not switched on yet (no Gemini key configured). "
        "In the meantime: use \"Check crop\" to photograph a sick leaf for a "
        "diagnosis, \"Risk forecast\" for a weather-based warning, and always "
        "follow the advisory shown with your result for exact products and doses."
    ),
    "mr": (
        "थेट सहायक अद्याप सुरू केलेला नाही (Gemini की सेट केलेली नाही). "
        "तोपर्यंत: निदानासाठी \"पीक तपासा\" मधून रोगट पानाचा फोटो घ्या, हवामान "
        "इशाऱ्यासाठी \"धोका अंदाज\" वापरा, आणि नेमके उत्पादन व मात्रेसाठी नेहमी "
        "निकालासोबतचा सल्ला पाळा."
    ),
    "hi": (
        "लाइव सहायक अभी चालू नहीं है (Gemini की सेट नहीं है)। तब तक: निदान के लिए "
        "\"फसल जाँचें\" से बीमार पत्ती की फोटो लें, मौसम चेतावनी के लिए \"जोखिम "
        "अनुमान\" का उपयोग करें, और सही उत्पाद व मात्रा के लिए हमेशा नतीजे के साथ "
        "दी गई सलाह मानें।"
    ),
    "bn": (
        "লাইভ সহায়ক এখনও চালু হয়নি (Gemini কী সেট করা নেই)। ততক্ষণ: রোগ নির্ণয়ে "
        "\"ফসল দেখুন\" থেকে অসুস্থ পাতার ছবি তুলুন, আবহাওয়া সতর্কতায় \"ঝুঁকির "
        "পূর্বাভাস\" ব্যবহার করুন, এবং সঠিক পণ্য ও মাত্রার জন্য সবসময় ফলাফলের সঙ্গে "
        "দেওয়া পরামর্শ মেনে চলুন।"
    ),
}

# History window sent to the model; older turns are dropped to bound cost.
_MAX_HISTORY = 12


def fallback_reply(language: str) -> str:
    return _FALLBACK.get(language, _FALLBACK["en"])


def _to_gemini_contents(history: list[dict], message: str) -> list[dict]:
    contents: list[dict] = []
    for turn in history[-_MAX_HISTORY:]:
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


def answer(message: str, history: list[dict], language: str) -> tuple[str, bool]:
    """Return ``(reply, live)``. ``live`` is False when the canned fallback ran."""
    if not settings.chat_enabled:
        return fallback_reply(language), False

    lang_name = _LANG_NAME.get(language, "English")
    system_text = f"{SYSTEM_PROMPT}\n\nRespond in {lang_name}."
    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": _to_gemini_contents(history, message),
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 512},
    }
    url = GEMINI_URL.format(model=settings.gemini_model)

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                url,
                params={"key": settings.gemini_api_key},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        reply = _extract_text(data)
        if reply:
            return reply, True
        log.warning("Gemini returned no usable text; using fallback")
    except httpx.HTTPStatusError as exc:
        log.warning("Gemini HTTP %s: %s", exc.response.status_code, exc.response.text[:300])
    except httpx.HTTPError as exc:
        log.warning("Gemini request failed: %s", exc)

    return fallback_reply(language), False


def _extract_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()
