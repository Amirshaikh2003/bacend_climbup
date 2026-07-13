"""
Gemini 2.0 Flash client — drop-in replacement for openrouter_client.

Exposes:
  - chat_completion(messages, max_tokens, temperature) -> str
      Same interface as openrouter_client so question_analyzer &
      answer_generator work without any changes.

  - chat_completion_with_images(messages, image_urls, max_tokens, temperature) -> str
      Multimodal call: downloads each image and sends as inlineData part
      so Gemini can actually SEE circuit diagrams and engineering figures.
"""

from __future__ import annotations

import base64
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ── SSL context (bypasses Windows cert-store issues) ─────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ── Errors ────────────────────────────────────────────────────────────────────
class GeminiError(RuntimeError):
    pass


# Alias so any existing except-clauses for OpenRouterError still work
OpenRouterError = GeminiError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = settings.GEMINI_API_KEY
    if not key:
        raise GeminiError("GEMINI_API_KEY is missing in backend/.env")
    return key


def _get_model() -> str:
    return getattr(settings, "GEMINI_MODEL", "gemini-3.1-flash-lite")


def _download_image_b64(url: str) -> Optional[tuple[str, str]]:
    """Download image from URL and return (base64_data, mime_type) or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
            # Normalise mime type
            if "jpeg" in content_type or "jpg" in content_type:
                mime = "image/jpeg"
            elif "png" in content_type:
                mime = "image/png"
            elif "webp" in content_type:
                mime = "image/webp"
            else:
                mime = "image/png"
            return base64.b64encode(raw).decode("utf-8"), mime
    except Exception as exc:
        logger.warning("Failed to download image %s: %s", url, exc)
        return None


def _build_contents(
    messages: List[Dict[str, str]],
    image_urls: Optional[List[str]] = None,
) -> tuple[list, Optional[dict]]:
    """
    Convert OpenAI-style messages → Gemini contents list.
    Optionally append images to the last user turn.

    Returns (contents, system_instruction_or_None).
    """
    system_parts: list[str] = []
    contents: list[dict] = []

    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")

        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})
        else:
            contents.append({"role": "user", "parts": [{"text": text}]})

    # If only system messages provided, convert to user turn
    if not contents and system_parts:
        contents.append({"role": "user", "parts": [{"text": "\n\n".join(system_parts)}]})

    # Attach images to the last user turn
    if image_urls:
        # Find the last user turn
        last_user_idx = None
        for idx in range(len(contents) - 1, -1, -1):
            if contents[idx]["role"] == "user":
                last_user_idx = idx
                break

        if last_user_idx is None:
            contents.append({"role": "user", "parts": []})
            last_user_idx = len(contents) - 1

        for url in image_urls:
            result = _download_image_b64(url)
            if result:
                b64_data, mime = result
                contents[last_user_idx]["parts"].append({
                    "inlineData": {"mimeType": mime, "data": b64_data}
                })
                logger.info("Attached image to Gemini request: %s", url[:60])
            else:
                # Fallback: just mention the URL in text
                contents[last_user_idx]["parts"].append({
                    "text": f"\n[Diagram/Image URL: {url}]"
                })

    system_instruction = None
    if system_parts:
        system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]}

    return contents, system_instruction


def _gemini_request(
    contents: list,
    system_instruction: Optional[dict],
    max_tokens: int,
    temperature: float,
    response_mime_type: Optional[str] = None,
    retries: int = 3,
) -> str:
    """Send a generateContent request to Gemini and return the text."""
    api_key = _get_api_key()
    model = _get_model()

    generation_config = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type

    payload: dict = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_instruction:
        payload["systemInstruction"] = system_instruction

    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                # Rate limited — wait and retry
                wait = 20 * (attempt + 1)
                logger.warning("Gemini rate limited (429). Waiting %ds before retry %d/%d…", wait, attempt + 1, retries)
                if attempt < retries:
                    time.sleep(wait)
                    continue
            raise GeminiError(f"Gemini HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise GeminiError(f"Gemini connection error: {exc.reason}") from exc

        # Parse response
        try:
            candidate = data["candidates"][0]
            finish_reason = candidate.get("finishReason", "")
            parts = candidate.get("content", {}).get("parts", [])
            if parts:
                return "".join(p.get("text", "") for p in parts if "text" in p) or ""
            if finish_reason == "MAX_TOKENS":
                raise GeminiError(
                    f"Gemini MAX_TOKENS reached. Usage: {data.get('usageMetadata', {})}"
                )
            # Empty response — retry
            if attempt < retries:
                logger.warning("Empty Gemini response (attempt %d), retrying…", attempt + 1)
                time.sleep(3)
                continue
            raise GeminiError(f"No text in Gemini response. Finish: {finish_reason}. Full: {data}")
        except GeminiError:
            raise
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiError(f"Unexpected Gemini response structure: {data}") from exc

    raise GeminiError("All Gemini retries exhausted")


# ── Public API ────────────────────────────────────────────────────────────────

def chat_completion(
    messages: List[Dict[str, str]],
    max_tokens: int = 8192,
    temperature: float = 0.25,
    response_mime_type: Optional[str] = None,
) -> str:
    """
    Drop-in replacement for openrouter_client.chat_completion.
    Used by question_analyzer and answer_generator unchanged.
    """
    contents, system_instruction = _build_contents(messages)
    return _gemini_request(contents, system_instruction, max_tokens, temperature, response_mime_type=response_mime_type)


def chat_completion_with_images(
    messages: List[Dict[str, str]],
    image_urls: List[str],
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """
    Multimodal call: attaches real images (downloaded from URLs) to the
    Gemini request so the model can visually analyze circuit diagrams,
    graphs, and engineering figures.
    """
    contents, system_instruction = _build_contents(messages, image_urls=image_urls)
    return _gemini_request(contents, system_instruction, max_tokens, temperature)


def fix_pdf_math_with_vision(
    image_bytes: bytes,
    prompt_text: str,
    max_tokens: int = 8192,
    temperature: float = 0.1,
) -> str:
    """
    Sends a raw image of a PDF page to Gemini to perfectly extract/fix math and text.
    """
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    
    contents = [{
        "role": "user",
        "parts": [
            {"text": prompt_text},
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": b64_img
                }
            }
        ]
    }]
    
    system_instruction = {
        "parts": [{"text": "You are an expert at perfectly reading question papers and converting math to LaTeX."}]
    }
    
    return _gemini_request(contents, system_instruction, max_tokens, temperature, response_mime_type="application/json")

