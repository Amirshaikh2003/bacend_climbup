"""
OpenRouter API Client for DeepSeek (Text) and Multimodal Fallback.
"""

import os
import json
import logging
import base64
import requests
from typing import List, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1/chat/completions"

def _get_api_key():
    key = getattr(settings, "OPENROUTER_API_KEY", None) or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is not set in environment.")
    return key

def _get_headers():
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://climbup.ai",
        "X-Title": "ClimbUP AI Engine"
    }

def chat_completion(messages: List[Dict[str, str]], max_tokens: int = 4096, temperature: float = 0.3) -> str:
    """Standard text generation using DeepSeek V3/Chat via OpenRouter."""
    payload = {
        "model": "deepseek/deepseek-chat", # DeepSeek V3 (High quality, massive tokens)
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    
    try:
        # Bypass SSL verification for robust local execution, just in case
        response = requests.post(OPENROUTER_API_BASE, headers=_get_headers(), json=payload, verify=False, timeout=120)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenRouter Text API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        raise e

def _get_base64_from_url(url: str) -> str:
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=10, verify=False)
    response.raise_for_status()
    return base64.b64encode(response.content).decode('utf-8')

def chat_completion_with_images(messages: List[Dict[str, str]], image_urls: List[str], max_tokens: int = 4096, temperature: float = 0.3) -> str:
    """Multimodal generation using Claude 3.5 Sonnet (Best for Vision/JSON) via OpenRouter."""
    vision_messages = []
    
    for msg in messages:
        if msg["role"] == "user":
            content = [{"type": "text", "text": msg["content"]}]
            for url in image_urls:
                try:
                    b64 = _get_base64_from_url(url)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }
                    })
                except Exception as e:
                    logger.warning(f"Failed to fetch image for OpenRouter Vision ({url}): {e}")
            vision_messages.append({"role": "user", "content": content})
        else:
            vision_messages.append(msg)
            
    payload = {
        "model": "anthropic/claude-3.5-sonnet", # Claude 3.5 Sonnet is the king of structured vision tasks
        "messages": vision_messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
            
    try:
        response = requests.post(OPENROUTER_API_BASE, headers=_get_headers(), json=payload, verify=False, timeout=120)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenRouter Vision API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        raise e
