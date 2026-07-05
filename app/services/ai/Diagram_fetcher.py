import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_SERPAPI_URL = "https://serpapi.com/search"
_TIMEOUT     = 15  # seconds


# ---------------------------------------------------------------------------
# Core Tavily API call
# ---------------------------------------------------------------------------

def _fetch_image_url(search_query: str) -> Optional[str]:
    """Return the first usable image URL for *search_query*, or None."""
    api_key = os.getenv("TAVILY_API_KEY")
    
    if not api_key:
        logger.warning("TAVILY_API_KEY not set")
        return None

    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": search_query + " diagram",
            "search_depth": "basic",
            "include_images": True,
            "max_results": 1
        }
        resp = requests.post(url, json=payload, timeout=_TIMEOUT, verify=False)
        resp.raise_for_status()
        
        images = resp.json().get("images", [])
        if images and isinstance(images[0], str) and images[0].startswith("http"):
            return images[0]
            
    except Exception as exc:
        logger.warning("Tavily Image fetch failed for %r: %s", search_query, exc)

    return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_image_link_from_serpapi(image_block: Dict[str, Any]) -> Optional[str]:
    """
    Given an image block dict, return a resolved image URL or None.

    Expected input:
        {
            "type": "image",
            "title": "...",
            "recommended_website": "...",
            "search_query": "..."
        }
    """
    if not isinstance(image_block, dict) or image_block.get("type") != "image":
        return None

    query = str(image_block.get("search_query") or image_block.get("title") or "").strip()
    return _fetch_image_url(query) if query else None


def replace_image_blocks_with_urls(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Walk payload["answer"] (list or {"answer": list}), resolve each image block,
    and add a "url" key if a URL was found.  The block type stays "image".

    Returns the mutated payload (also mutates in-place for efficiency).
    """
    if not isinstance(payload, dict):
        return payload

    answer_field = payload.get("answer")

    # Support both flat list and wrapped {"answer": [...]} shapes
    if isinstance(answer_field, dict):
        blocks: List[Dict[str, Any]] = answer_field.get("answer", [])
        _write_back = lambda updated: answer_field.update({"answer": updated})  # noqa: E731
    elif isinstance(answer_field, list):
        blocks = answer_field
        _write_back = lambda updated: payload.update({"answer": updated})  # noqa: E731
    else:
        return payload

    updated: List[Dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "image":
            url = get_image_link_from_serpapi(block)
            block = {**block, "url": url} if url else block  # non-destructive copy
        updated.append(block)

    _write_back(updated)
    return payload


# ---------------------------------------------------------------------------
# Dev smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = {
        "answer": [
            {"type": "text",  "content": "## Intro\nThe OSI model..."},
            {
                "type": "image",
                "title": "OSI Model Layered Diagram",
                "recommended_website": "GeeksforGeeks, Tutorialspoint, Wikipedia",
                "search_query": "OSI model layered structure diagram",
            },
            {"type": "text", "content": "## Layers\n### 1. Physical Layer..."},
        ]
    }
    result = replace_image_blocks_with_urls(sample)
    print(json.dumps(result, indent=2, ensure_ascii=False))