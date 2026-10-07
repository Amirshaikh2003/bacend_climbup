import json
import logging
import urllib.request
import urllib.error
import urllib3
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.services.supabase_service import _session, SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# We use Gemini's free embedding model for vectorization
GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"

def _get_api_key() -> str:
    # Use GEMINI_API_KEY from settings
    key = getattr(settings, "GEMINI_API_KEY", None)
    import os
    if not key:
        key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not set.")
    return key

def get_embedding(text: str) -> List[float]:
    """Calls Gemini API to get a 768-dimensional vector embedding for the given text."""
    api_key = _get_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/{GEMINI_EMBEDDING_MODEL}:embedContent?key={api_key}"
    
    payload = {
        "model": GEMINI_EMBEDDING_MODEL,
        "content": {
            "parts": [{"text": text}]
        }
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode())
            embedding = result.get("embedding", {}).get("values", [])
            if not embedding:
                logger.error(f"Failed to extract embedding from Gemini API. Result: {result}")
            return embedding
    except urllib.error.URLError as e:
        logger.error(f"Gemini Embedding request failed: {e}")
        return []

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Splits a long string of text into overlapping chunks."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

def save_note_embeddings(user_id: str, subject_id: str, file_name: str, extracted_text: str) -> bool:
    """Chunks the text, gets embeddings, and saves to Supabase notes_embeddings table."""
    if not extracted_text.strip():
        logger.info(f"No text extracted for {file_name}, skipping embeddings.")
        return False
        
    chunks = chunk_text(extracted_text)
    
    records = []
    for chunk in chunks:
        vector = get_embedding(chunk)
        if not vector:
            continue
            
        records.append({
            "user_id": user_id,
            "subject_id": subject_id,
            "file_name": file_name,
            "content": chunk,
            "embedding": vector
        })
        
    if not records:
        return False
        
    # Bulk insert to Supabase
    url = f"{SUPABASE_URL}/rest/v1/notes_embeddings"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    try:
        # Use requests for Supabase REST API
        import requests
        response = requests.post(url, headers=headers, json=records, verify=False, timeout=30)
        response.raise_for_status()
        logger.info(f"Successfully saved {len(records)} embedding chunks for {file_name}.")
        return True
    except Exception as e:
        logger.error(f"Failed to save embeddings to Supabase: {e}")
        return False

def search_notes(user_id: str, subject_id: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Searches the database for the most relevant note chunks using Supabase pgvector RPC."""
    query_vector = get_embedding(query)
    if not query_vector:
        return []
        
    url = f"{SUPABASE_URL}/rest/v1/rpc/match_notes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "query_embedding": query_vector,
        "match_threshold": 0.5, # Minimum similarity score
        "match_count": top_k,
        "p_user_id": user_id,
        "p_subject_id": subject_id
    }
    
    try:
        import requests
        response = requests.post(url, headers=headers, json=payload, verify=False, timeout=15)
        if response.status_code != 200:
            logger.error(f"Supabase RPC match_notes failed: {response.text}")
            return []
        
        return response.json()
    except Exception as e:
        logger.error(f"Search notes failed: {e}")
        return []

import time
from app.services.ai.gemini_client import categorize_pdf_with_vision


def search_file_notes(user_id: str, file_name: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Searches the database for the most relevant note chunks strictly within a specific file."""
    query_vector = get_embedding(query)
    if not query_vector:
        return []
        
    url = f"{SUPABASE_URL}/rest/v1/rpc/match_file_notes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "query_embedding": query_vector,
        "match_threshold": 0.5,
        "match_count": top_k,
        "p_user_id": user_id,
        "p_file_name": file_name
    }
    
    try:
        import requests
        response = requests.post(url, headers=headers, json=payload, verify=False, timeout=15)
        if response.status_code != 200:
            logger.error(f"Supabase RPC match_file_notes failed: {response.text}")
            return []
        
        return response.json()
    except Exception as e:
        logger.error(f"Search file notes failed: {e}")
        return []

def process_and_embed_document(user_id: str, subject_id: str, file_name: str, file_bytes: bytes, mime_type: str):
    """
    Background worker: Extracts text (using OCR for handwriting if needed), 
    then chunks and embeds the entire document.
    """
    extracted_full_text = ""
    logger.info(f"Starting background RAG processing for {file_name}...")
    
    if mime_type == "application/pdf":
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(doc)
            
            for page_num in range(total_pages):
                page_text = doc[page_num].get_text()
                if len(page_text.strip()) > 50:
                    extracted_full_text += f"\n--- Page {page_num+1} ---\n{page_text}"
                else:
                    # Likely handwritten or scanned image. Use Gemini Vision OCR.
                    try:
                        pix = doc[page_num].get_pixmap()
                        img_bytes = pix.tobytes("png")
                        
                        prompt = "Extract all the handwritten or printed notes from this image. Keep the technical terms intact. Format as clear readable text."
                        ocr_text = categorize_pdf_with_vision(img_bytes, prompt, max_tokens=1000)
                        
                        extracted_full_text += f"\n--- Page {page_num+1} (OCR) ---\n{ocr_text}"
                        
                        # Respect Gemini Free Tier limits (~15 RPM)
                        time.sleep(4)
                    except Exception as ocr_err:
                        logger.error(f"OCR failed for page {page_num}: {ocr_err}")
                        
            doc.close()
        except Exception as e:
            logger.error(f"PyMuPDF processing failed for RAG: {e}")
            return
            
    elif mime_type.startswith("image/"):
        # Single image handwritten note
        try:
            prompt = "Extract all the handwritten or printed notes from this image. Format as clear readable text."
            extracted_full_text = categorize_pdf_with_vision(file_bytes, prompt, max_tokens=1500)
        except Exception as e:
            logger.error(f"Vision OCR failed for image RAG: {e}")
            return

    if extracted_full_text.strip():
        save_note_embeddings(user_id, subject_id, file_name, extracted_full_text)
    else:
        logger.warning(f"No content extracted for {file_name} to embed.")
