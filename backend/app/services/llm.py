"""Thin wrapper over any OpenAI-compatible endpoint (Groq, Gemini, OpenRouter, Ollama, OpenAI...).

Everything degrades gracefully: when no model is configured the callers fall back to
non-AI behaviour, so the app stays fully usable without any paid key.
"""
import json
import logging
import re

from app.core.config import settings

log = logging.getLogger(__name__)


def is_configured() -> bool:
    local = any(h in settings.openai_base_url for h in ("localhost", "127.0.0.1"))
    return bool(settings.openai_api_key) or local


def chat_json(system: str, user: str, max_tokens: int = 900) -> dict | None:
    """Return a parsed JSON object, or None if no model is configured or the call fails."""
    if not is_configured():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key or "ollama",
            base_url=settings.openai_base_url,
            timeout=45,
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        match = re.search(r"\{.*\}", text, re.S)  # tolerate prose / code fences around the JSON
        return json.loads(match.group(0)) if match else None
    except Exception:  # noqa: BLE001 - provider errors must never crash a request
        log.exception("LLM call failed")
        return None
