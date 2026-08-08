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

def _fetch_candidate_image_urls(search_query: str) -> List[str]:
    """Return up to 3 usable image URLs for *search_query*."""
    api_key = os.getenv("TAVILY_API_KEY")
    
    if not api_key:
        logger.warning("TAVILY_API_KEY not set")
        return []

    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": search_query + " diagram or flowchart",
            "search_depth": "basic",
            "include_images": True,
            "max_results": 5
        }
        resp = requests.post(url, json=payload, timeout=_TIMEOUT, verify=False)
        resp.raise_for_status()
        
        images = resp.json().get("images", [])
        
        blocked_keywords = [
            "pinterest", "amazon", "flipkart", "shutterstock", "istockphoto", "gettyimages", 
            "freepik", "alamy", "123rf", "dreamstime", "facebook", "instagram", "twitter", 
            "tiktok", "news", "stock", "vector", "pngtree", "vecteezy", "ebay", "etsy"
        ]
        
        valid_urls = []
        for img in images:
            if isinstance(img, str) and img.startswith("http"):
                img_lower = img.lower()
                # Ensure the image is NOT from a stock photo or e-commerce site
                if not any(blocked in img_lower for blocked in blocked_keywords):
                    valid_urls.append(img)
                    if len(valid_urls) >= 3:
                        break
                        
        return valid_urls
            
    except Exception as exc:
        logger.warning("Tavily Image fetch failed for %r: %s", search_query, exc)

    return []

def _verify_image_with_vision(query: str, urls: List[str]) -> Optional[str]:
    """Uses Gemini Vision to evaluate which diagram is the most accurate."""
    from app.services.ai.gemini_client import chat_completion_with_images
    
    if not urls:
        return None
    if len(urls) == 1:
        return urls[0]
        
    system_prompt = (
        "You are an expert Engineering AI. You are given a technical search query and a few candidate images. "
        "Select the image that most accurately represents the query (e.g., correct P-V diagram, correct circuit, etc.). "
        "Return exactly the URL string of the best image. Do not return any other text. If none are good, return the first one."
    )
    
    prompt = f"Search Query: {query}\n\nCandidate URLs:\n"
    for i, u in enumerate(urls):
        prompt += f"{i+1}. {u}\n"
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    try:
        best_url = chat_completion_with_images(messages, image_urls=urls, max_tokens=100, temperature=0.1).strip()
        if best_url in urls:
            return best_url
        return urls[0]
    except Exception as e:
        logger.warning(f"Vision verification failed: {e}")
        return urls[0]


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
    if not query:
        return None
        
    candidates = _fetch_candidate_image_urls(query)
    best_url = _verify_image_with_vision(query, candidates)
    return best_url


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
            if not url:
                logger.info(f"Dropping image block, no URL found for: {block.get('search_query')}")
                continue  # Drop the block entirely if no image is found
            block = {**block, "url": url}
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