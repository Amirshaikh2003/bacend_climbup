import logging
from fastapi import APIRouter, HTTPException
from app.schemas.verification import AnswerVerificationRequest, AnswerVerificationResponse
from app.services.ai.answer_verifier import verify_student_answer

logger = logging.getLogger(__name__)

router = APIRouter()

import json

@router.post("/verify-answer", response_model=AnswerVerificationResponse)
async def verify_answer_endpoint(request: AnswerVerificationRequest):
    try:
        answer_str = ""
        if isinstance(request.answer, list):
            # Try to extract content from blocks if it's a list of blocks
            extracted = []
            for block in request.answer:
                if isinstance(block, dict) and "content" in block:
                    extracted.append(str(block.get("content", "")))
            answer_str = "\n".join(extracted) if extracted else json.dumps(request.answer)
        elif isinstance(request.answer, dict):
            answer_str = json.dumps(request.answer)
        else:
            answer_str = str(request.answer)

        # Pass the question and stringified answer to the Gemini verifier service
        result = verify_student_answer(question=request.question, answer=answer_str)
        
        return AnswerVerificationResponse(
            is_valid=result["is_valid"],
            reason=result["reason"]
        )
    except Exception as e:
        logger.error(f"Answer verification endpoint failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process verification request")
