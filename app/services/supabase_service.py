import json
import os
import urllib.error
import urllib.request
from typing import Any

from dotenv import load_dotenv

from app.core.config import BASE_DIR


load_dotenv(BASE_DIR / ".env")


class SupabaseStorageError(RuntimeError):
    pass


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
    request = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        },
        method="POST",
    )

    import ssl
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as response:
            result = json.loads(response.read().decode("utf-8") or "[]")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SupabaseStorageError(
            f"Supabase insert failed for {table}: HTTP {exc.code} {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SupabaseStorageError(
            f"Cannot connect to Supabase for {table}: {exc.reason}"
        ) from exc

    if isinstance(result, list) and result:
        return result[0]
    if isinstance(result, dict):
        return result
    raise SupabaseStorageError(f"Supabase returned no row for {table}")


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
    answer: dict[str, Any],
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
    answer: dict[str, Any],
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
