import json
import logging
import urllib.error
import urllib.request
from typing import Dict, List

from app.core.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    pass


def chat_completion(
    messages: List[Dict[str, str]],
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.25,
) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER API key is missing in backend/.env")

    models_to_try = [model] if model else settings.OPENROUTER_MODELS_POOL
    
    import random
    if not model and len(models_to_try) > 1:
        models_to_try = list(models_to_try)
        random.shuffle(models_to_try)

    last_error: Exception | None = None
    for m in dict.fromkeys(m for m in models_to_try if m):
        try:
            return _chat_completion_for_model(
                model=m,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            last_error = exc
            logger.warning("OpenRouter model %s failed: %s", m, exc)

    raise OpenRouterError(f"All OpenRouter models failed: {last_error}")


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
        OPENROUTER_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": settings.APP_NAME,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
        raise OpenRouterError(f"HTTP {exc.code}: {error_body}") from exc

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError(f"Unexpected OpenRouter response: {data}") from exc
