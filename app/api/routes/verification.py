import logging
from fastapi import APIRouter, HTTPException
from app.schemas.verification import AnswerVerificationRequest, AnswerVerificationResponse
from app.services.ai.answer_verifier import verify_student_answer

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/verify-answer", response_model=AnswerVerificationResponse)
async def verify_answer_endpoint(request: AnswerVerificationRequest):
    try:
        # Pass the question and answer to the Gemini verifier service
        result = verify_student_answer(question=request.question, answer=request.answer)
        
        return AnswerVerificationResponse(
            is_valid=result["is_valid"],
            reason=result["reason"]
        )
    except Exception as e:
        logger.error(f"Answer verification endpoint failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process verification request")
