import json
import logging
import urllib.error
import urllib.request
from typing import Dict, List

from app.core.config import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(RuntimeError):
    pass


def chat_completion(
    messages: List[Dict[str, str]],
    max_tokens: int = 4096,
    temperature: float = 0.25,
) -> str:
    if not settings.GROQ_API_KEY:
        raise GroqError("GROQ API key is missing in backend/.env")

    last_error: Exception | None = None
    models = [settings.GROQ_MODEL, settings.GROQ_MODEL_FALLBACK]

    for model in dict.fromkeys(model for model in models if model):
        try:
            return _chat_completion_for_model(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            last_error = exc
            logger.warning("Groq model %s failed: %s", model, exc)

    raise GroqError(f"All Groq models failed: {last_error}")


def _chat_completion_for_model(
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    request = urllib.request.Request(
        GROQ_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    import ssl
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise GroqError(f"HTTP {exc.code}: {error_body}") from exc

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise GroqError(f"Unexpected Groq response: {data}") from exc
