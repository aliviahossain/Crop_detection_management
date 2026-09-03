"""POST /chat -- the floating in-app assistant.

Thin wrapper over ``services.chat``. The Gemini key stays server-side; the
browser only ever sees the reply. Stateless: the client sends recent history
each turn, so there is nothing to persist here.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.schemas import ChatRequest, ChatResponse
from app.services import chat as chat_service
from app.services.translate import normalise_language

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="Ask the CropGuard assistant")
def chat(req: ChatRequest) -> ChatResponse:
    lang = normalise_language(req.language)
    reply, live = chat_service.answer(
        message=req.message,
        history=[m.model_dump() for m in req.history],
        language=lang,
    )
    return ChatResponse(reply=reply, language=lang, live=live)


@router.get("/status", summary="Whether the live assistant is configured")
def status() -> dict:
    return {
        "enabled": settings.chat_enabled,
        "model": settings.gemini_model if settings.chat_enabled else None,
        "note": (
            "Live Gemini answers are on."
            if settings.chat_enabled
            else "No GEMINI_API_KEY set; the assistant runs canned fallback replies."
        ),
    }
