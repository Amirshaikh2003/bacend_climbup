import json
import os
import requests
import urllib3
from typing import Any
from functools import lru_cache

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv

from app.core.config import BASE_DIR


load_dotenv(BASE_DIR / ".env")

class SupabaseStorageError(RuntimeError):
    pass

# Global session for connection pooling
_session = requests.Session()
_session.verify = False


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _require_row_id(row: dict[str, Any], table: str, *keys: str) -> str:
    value = _first_present(row, *keys)
    if value is None:
        available = ", ".join(sorted(row.keys())) or "no columns"
        expected = ", ".join(keys)
        raise SupabaseStorageError(
            f"Supabase {table} insert returned no usable id. "
            f"Expected one of: {expected}. Returned columns: {available}"
        )
    return str(value)


SUPABASE_PROJECT_ID = os.getenv("SUPABASE_PROJECT_ID", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
if not SUPABASE_URL and SUPABASE_PROJECT_ID:
    SUPABASE_URL = f"https://{SUPABASE_PROJECT_ID}.supabase.co"

SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.getenv("SUPABASE_ANON_KEY", "").strip()
    or os.getenv("SUPABASE_KEY", "").strip()
)


def _require_config() -> None:
    has_placeholder = any(
        value.startswith("YOUR_")
        for value in (SUPABASE_PROJECT_ID, SUPABASE_URL, SUPABASE_KEY)
        if value
    )
    if not SUPABASE_URL or not SUPABASE_KEY or has_placeholder:
        raise SupabaseStorageError(
            "Set real SUPABASE_PROJECT_ID, SUPABASE_URL, and SUPABASE_SERVICE_ROLE_KEY in backend/.env"
        )


def _insert(table: str, payload: dict[str, Any]) -> dict[str, Any]:
    _require_config()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Prefer": "return=representation",
    }
    try:
        response = _session.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            json=payload,
            headers=headers,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.HTTPError as exc:
        raise SupabaseStorageError(
            f"Supabase insert failed for {table}: HTTP {exc.response.status_code} {exc.response.text}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise SupabaseStorageError(f"Cannot connect to Supabase for {table}: {str(exc)}") from exc

    if isinstance(result, list) and result:
        return result[0]
    if isinstance(result, dict):
        return result
    return {}
def _delete(table: str, match_column: str, match_value: str) -> bool:
    _require_config()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    try:
        response = _session.delete(
            f"{SUPABASE_URL}/rest/v1/{table}?{match_column}=eq.{match_value}",
            headers=headers,
            timeout=60
        )
        return response.status_code in (200, 204)
    except requests.exceptions.HTTPError as exc:
        import logging
        logging.getLogger(__name__).error(f"Supabase delete failed for {table}: HTTP {exc.response.status_code} {exc.response.text}")
        return False
    except requests.exceptions.RequestException as exc:
        import logging
        logging.getLogger(__name__).error(f"Cannot connect to Supabase for {table}: {str(exc)}")
        return False

def delete_question_paper_cascade(paper_id: str) -> bool:
    """Attempts to delete a question paper and its associated questions and ai_answers."""
    # 1. Fetch all questions for this paper to get their IDs
    questions = _select("questions", f"paper_id=eq.{paper_id}")
    
    # 2. Delete all ai_answers for each question
    for q in questions:
        q_id = q.get("id") or q.get("question_id")
        if q_id:
            _delete("ai_answers", "question_id", q_id)
            
    # 3. Delete all questions for this paper
    _delete("questions", "paper_id", paper_id)
    
    # 4. Delete the question paper itself
    return _delete("question_papers", "paper_id", paper_id) or _delete("question_papers", "id", paper_id)


def _select(table: str, query: str = "") -> list[dict[str, Any]]:
    _require_config()
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if query:
        url += f"?{query}"
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    }

    try:
        response = _session.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.HTTPError as exc:
        raise SupabaseStorageError(
            f"Supabase select failed for {table}: HTTP {exc.response.status_code} {exc.response.text}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise SupabaseStorageError(
            f"Cannot connect to Supabase for {table}: {str(exc)}"
        ) from exc

    return result if isinstance(result, list) else []


@lru_cache(maxsize=128)
def get_universities() -> list[dict[str, Any]]:
    return _select("universities", "select=university_id,university_name")

@lru_cache(maxsize=128)
def get_branches(university_id: str) -> list[dict[str, Any]]:
    return _select("branches", f"university_id=eq.{university_id}&select=branch_id,branch_name")

@lru_cache(maxsize=128)
def get_semesters(branch_id: str) -> list[dict[str, Any]]:
    # Semesters are 1 to 8 according to the DB schema
    return [{"semester_id": i, "semester_number": i} for i in range(1, 9)]

@lru_cache(maxsize=128)
def get_subjects(branch_id: str, semester: int) -> list[dict[str, Any]]:
    return _select("subjects", f"branch_id=eq.{branch_id}&semester=eq.{semester}&select=subject_id,subject_name,subject_code")

def get_all_question_papers() -> list[dict[str, Any]]:
    # Select question papers along with their subjects for display
    # Ordering by year descending since created_at doesn't exist
    return _select("question_papers", "select=*,subjects(subject_name)&order=year.desc")


def create_question_paper(
    *,
    subject_id: str,
    paper_title: str,
    year: int,
    exam_type: str,
    duration: int,
    total_marks: int,
    paper_url: str | None = None,
) -> dict[str, Any]:
    payload = {
        "subject_id": subject_id,
        "paper_title": paper_title,
        "year": year,
        "exam_type": exam_type,
        "duration": duration,
        "total_marks": total_marks,
    }
    if paper_url:
        payload["paper_url"] = paper_url
        
    row = _insert(
        "question_papers",
        payload,
    )
    row["paper_id"] = _require_row_id(row, "question_papers", "paper_id", "id")
    return row


def create_question(
    *,
    paper_id: str,
    question_number: str,
    module: str,
    marks: int,
    difficulty: str,
    question_text: str,
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "paper_id": paper_id,
        "question_number": question_number,
        "module": module,
        "marks": marks,
        "difficulty": difficulty,
        "question_text": question_text,
    }
    if image_urls:
        payload["image_urls"] = image_urls
    try:
        return _insert("questions", payload)
    except SupabaseStorageError as error:
        raise SupabaseStorageError(
            f"Question upload failed for paper_id={paper_id}, "
            f"question_number={question_number}: {error}"
        ) from error


def store_ai_answer(
    *,
    question_id: str,
    answer: dict[str, Any] | str,
    ai_model: str = "openrouter",
) -> dict[str, Any]:
    return _insert(
        "ai_answers",
        {
            "question_id": question_id,
            "answer": answer,
            "ai_model": ai_model,
        },
    )


def store_question_answer(
    *,
    paper_id: str,
    question_text: str,
    answer: dict[str, Any] | str,
    question_number: str = "Q1",
    module: str = "Module 1",
    marks: int = 5,
    difficulty: str = "Easy",
    ai_model: str = "openrouter",
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    question_row = create_question(
        paper_id=paper_id,
        question_number=question_number,
        module=module,
        marks=marks,
        difficulty=difficulty,
        question_text=question_text,
        image_urls=image_urls,
    )
    question_id = _require_row_id(question_row, "questions", "question_id", "id")
    answer_row = store_ai_answer(
        question_id=question_id,
        answer=answer,
        ai_model=ai_model,
    )
    answer_id = _require_row_id(answer_row, "ai_answers", "answer_id", "ai_answer_id", "id")

    return {
        "paper_id": paper_id,
        "question_id": question_id,
        "answer_id": answer_id,
        "question_row": question_row,
        "answer_row": answer_row,
    }
