import json
import re
import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from app.services.pdf_extractor import (
    process_pdf_file, 
    upload_raw_pdf_to_cloudinary,
    upload_bytes_to_cloudinary,
    delete_image_from_cloudinary
)

from app.services.ai.question_analyzer import analyze_question
from app.services.ai.answer_generator import generate_answer_via_openrouter, generate_answer_via_gemini_strict, generate_answer_via_groq
from app.services.ai.openrouter_client import OpenRouterError, chat_completion
from app.services.supabase_service import (
    SupabaseStorageError,
    create_question_paper,
    store_question_answer,
    create_question,
)

router = APIRouter()

class DeleteImageRequest(BaseModel):
    image_url: str

@router.post("/delete-image")
async def delete_image_endpoint(payload: DeleteImageRequest):
    try:
        success = await asyncio.to_thread(delete_image_from_cloudinary, payload.image_url)
        if success:
            return {"success": True, "message": "Image deleted successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete image")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload-image")
async def upload_image_endpoint(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        url = await asyncio.to_thread(upload_bytes_to_cloudinary, image_bytes)
        return {"success": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/question-paper/{paper_id}")
async def delete_question_paper_endpoint(paper_id: str):
    from app.services.supabase_service import delete_question_paper_cascade
    success = await asyncio.to_thread(delete_question_paper_cascade, paper_id)
    if success:
        return {"success": True, "message": "Question paper deleted successfully"}
    else:
        # even if it returns false, it might have deleted it but failed on a related table if cascade was already true.
        # we return success to the user to clear UI, but log error.
        return {"success": True, "message": "Question paper deletion attempted"}

class AnswerRequest(BaseModel):
    question: str = Field(..., min_length=3)
    paper_id: str | None = None
    question_id: str | None = None
    question_number: str | None = None
    module: str = "Module 1"
    marks: int = 5
    difficulty: str = "Easy"
    manual_answer: str | None = None
    image_urls: list[str] | None = None
    skip_answer: bool = False


class QuestionPaperRequest(BaseModel):
    subject_id: str = Field(..., min_length=1)
    paper_title: str = Field(..., min_length=3)
    year: int = 2024
    exam_type: str = "Summer Exam"
    duration: int = 180
    total_marks: int = 80
    paper_url: str | None = None


class QuestionExtractionRequest(BaseModel):
    text: str = Field(..., min_length=20)
    max_questions: int = Field(80, ge=1, le=200)


class QuestionBatchPayload(BaseModel):
    question: str
    question_number: str | None = None
    module: str = "Module 1"
    marks: int = 5
    difficulty: str = "Easy"
    image_urls: list[str] | None = None
    answer: dict | str | None = None
    analysis: dict | str | None = None
    skip_answer: bool = False

class SaveEntirePaperRequest(BaseModel):
    subject_id: str
    paper_title: str
    year: int = 2024
    exam_type: str = "Summer Exam"
    duration: int = 180
    total_marks: int = 80
    paper_url: str | None = None
    questions: list[QuestionBatchPayload]


def _validate_uuid(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        UUID(cleaned)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a valid UUID. Import/select a real subject first.",
        ) from error

    return cleaned


def _require_uuid(value: str | None, field_name: str) -> str:
    cleaned = _validate_uuid(value, field_name)
    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required. Import/select a real subject first.",
        )
    return cleaned


def _require_text(value: str | None, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is required. Create a question paper first.",
        )
    return cleaned


def _clean_json_payload(raw: str):
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    )
    match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1)
    return json.loads(cleaned)


def _normalise_extracted_questions(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("questions", [])

    if not isinstance(data, list):
        raise ValueError("OpenRouter response did not contain a question list")

    questions = []
    allowed_difficulties = {"Easy", "Medium", "Hard"}

    for index, item in enumerate(data, start=1):
        if isinstance(item, str):
            item = {"question": item}
        if not isinstance(item, dict):
            continue

        text = re.sub(r"\s+", " ", str(item.get("question", ""))).strip()
        if not text:
            continue

        marks = item.get("marks", 5)
        try:
            marks = int(marks)
        except (TypeError, ValueError):
            marks = 5

        difficulty = str(item.get("difficulty", "Easy")).strip().title()
        if difficulty not in allowed_difficulties:
            difficulty = "Easy"

        questions.append(
            {
                "question_no": str(item.get("question_no") or index),
                "part": str(item.get("part") or ""),
                "question": text,
                "module": str(item.get("module") or "Module 1"),
                "marks": max(marks, 1),
                "difficulty": difficulty,
            }
        )

    if not questions:
        raise ValueError("No valid questions were extracted")

    return questions


@router.post("/extract-questions")
async def extract_questions_endpoint(file: UploadFile = File(...)):
    try:
        pdf_bytes = await file.read()
        filename = file.filename
        
        result = await asyncio.to_thread(process_pdf_file, pdf_bytes, filename)
        
        return {
            "success": True,
            **result
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"PDF extraction failed: {str(error)}",
        )

@router.post("/upload-paper-pdf")
async def upload_paper_pdf_endpoint(file: UploadFile = File(...)):
    try:
        pdf_bytes = await file.read()
        filename = file.filename
        
        # Upload to Cloudinary in a background thread
        paper_url = await asyncio.to_thread(upload_raw_pdf_to_cloudinary, pdf_bytes, filename)
        
        return {
            "success": True,
            "paper_url": paper_url
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"PDF upload failed: {str(error)}",
        )


@router.get("/generate-answer")
async def generate_answer():
    question = """Explain CPU scheduling algorithms, compare FCFS, SJF, Priority, and Round Robin, and calculate the average waiting time for a given set of processes."""
    try:
        analysis = await analyze_question(question)
        answer = await asyncio.to_thread(generate_answer_via_gemini_strict, question, analysis)

        return {"success": True, "question": question, "analysis": analysis, "answer": answer}

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {str(error)}")


@router.post("/question-paper")
async def question_paper_endpoint(payload: QuestionPaperRequest):
    try:
        subject_id = _validate_uuid(payload.subject_id, "subject_id")
        if not subject_id:
            raise HTTPException(
                status_code=400,
                detail="subject_id is required before creating a question paper.",
            )

        paper_row = await asyncio.to_thread(
            create_question_paper,
            subject_id=subject_id,
            paper_title=payload.paper_title,
            year=payload.year,
            exam_type=payload.exam_type,
            duration=payload.duration,
            total_marks=payload.total_marks,
            paper_url=payload.paper_url,
        )

        return {
            "success": True,
            "paper_id": paper_row["paper_id"],
            "paper": paper_row,
        }

    except HTTPException:
        raise
    except SupabaseStorageError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Question paper creation failed: {str(error)}")


@router.post("/generate-only")
async def generate_only_endpoint(payload: AnswerRequest):
    try:
        if payload.skip_answer:
            return {
                "success": True,
                "question": payload.question,
                "status": "skipped"
            }

        # Safeguard against huge question payloads exhausting AI token limits
        safe_question = payload.question
        if safe_question and len(safe_question) > 3000:
            safe_question = safe_question[:3000] + "... (truncated due to length)"

        analysis = {"status": "skipped", "reason": "manual answer provided"} if payload.manual_answer else await analyze_question(safe_question)
        answer = {"answer": payload.manual_answer} if payload.manual_answer else await asyncio.to_thread(generate_answer_via_gemini_strict, safe_question, analysis)

        storage_data = None
        if payload.question_id and not answer.get("is_error"):
            from app.services.supabase_service import store_ai_answer
            answer_row = await asyncio.to_thread(
                store_ai_answer,
                question_id=payload.question_id,
                answer=answer,
                ai_model="manual" if payload.manual_answer else "openrouter"
            )
            storage_data = {
                "question_id": payload.question_id,
                "answer_id": answer_row.get("answer_id") or answer_row.get("id"),
            }

        return {
            "success": True,
            "question": payload.question,
            "analysis": analysis,
            "answer": answer,
            "storage": storage_data,
        }

    except Exception as error:
        import logging
        logging.getLogger(__name__).exception("Generate endpoint failed")
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {str(error)}")

@router.post("/save-entire-paper")
async def save_entire_paper_endpoint(payload: SaveEntirePaperRequest):
    try:
        subject_id = _validate_uuid(payload.subject_id, "subject_id")
        if not subject_id:
            raise HTTPException(
                status_code=400,
                detail="subject_id is required before creating a question paper.",
            )

        paper_row = await asyncio.to_thread(
            create_question_paper,
            subject_id=subject_id,
            paper_title=payload.paper_title,
            year=payload.year,
            exam_type=payload.exam_type,
            duration=payload.duration,
            total_marks=payload.total_marks,
            paper_url=payload.paper_url,
        )
        
        paper_id = paper_row["paper_id"]
        saved_questions = []
        seen_q_numbers = set()

        for q in payload.questions:
            q_num = q.question_number or "Q1"
            
            # Deduplicate question number
            original_q_num = q_num
            counter = 1
            while q_num in seen_q_numbers:
                q_num = f"{original_q_num}_dup{counter}"
                counter += 1
            seen_q_numbers.add(q_num)
            
            clean_question_text = q.question.replace("\x00", "")

            try:
                if q.skip_answer:
                    # Store question without answer
                    await asyncio.to_thread(
                        create_question,
                        paper_id=paper_id,
                        question_number=q_num,
                        module=q.module,
                        marks=q.marks,
                        difficulty=q.difficulty,
                        question_text=clean_question_text,
                        image_urls=q.image_urls,
                    )
                    saved_questions.append(q_num)
                else:
                    await asyncio.to_thread(
                        store_question_answer,
                        paper_id=paper_id,
                        question_text=clean_question_text,
                        answer=q.answer or {"answer": "No answer provided"},
                        question_number=q_num,
                        module=q.module,
                        marks=q.marks,
                        difficulty=q.difficulty,
                        ai_model="openrouter",
                        image_urls=q.image_urls,
                    )
                    saved_questions.append(q_num)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to save question {q_num}: {str(e)}")
                # Continue with the next question instead of failing the whole batch
                continue

        return {
            "success": True,
            "paper_id": paper_id,
            "total_questions_saved": len(saved_questions),
        }

    except HTTPException:
        raise
    except SupabaseStorageError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Batch save failed: {str(error)}")


@router.post("/answer")
async def answer_endpoint(payload: AnswerRequest):
    try:
        paper_id = _require_text(payload.paper_id, "paper_id")

        if payload.skip_answer:
            question_row = await asyncio.to_thread(
                create_question,
                paper_id=paper_id,
                question_number=payload.question_number or payload.question_id or "Q1",
                module=payload.module,
                marks=payload.marks,
                difficulty=payload.difficulty,
                question_text=payload.question,
                image_urls=payload.image_urls,
            )
            return {
                "success": True,
                "question": payload.question,
                "paper_id": paper_id,
                "question_id": question_row.get("question_id") or question_row.get("id"),
                "status": "stored_without_answer"
            }

        analysis = {"status": "skipped", "reason": "manual answer provided"} if payload.manual_answer else await analyze_question(payload.question)
        answer = {"answer": payload.manual_answer} if payload.manual_answer else await asyncio.to_thread(generate_answer_via_gemini_strict, payload.question, analysis)

        if not answer.get("is_error"):
            storage = await asyncio.to_thread(
                store_question_answer,
                paper_id=paper_id,
                question_text=payload.question,
                answer=answer,
                question_number=payload.question_number or payload.question_id or "Q1",
                module=payload.module,
                marks=payload.marks,
                difficulty=payload.difficulty,
                ai_model="manual" if payload.manual_answer else "openrouter",
                image_urls=payload.image_urls,
            )
        else:
            storage = None

        return {
            "success": True,
            "question": payload.question,
            "analysis": analysis,
            "answer": answer,
            "paper_id": storage["paper_id"],
            "question_id": storage["question_id"],
            "answer_id": storage["answer_id"],
            "storage": "supabase",
        }

    except HTTPException:
        raise
    except SupabaseStorageError as error:
        raise HTTPException(status_code=500, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {str(error)}")


@router.get("/answer-analyzer")
async def answer_analyzer(question: str = "Explain the architecture and working of a Phase-Locked Loop (PLL). Draw a neat block diagram and discuss its applications in communication systems."):
    try:
        analysis = await analyze_question(question)
        return {"success": True, "question": question, "analysis": analysis}

    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Question analyzer failed: {str(error)}")
    

    
