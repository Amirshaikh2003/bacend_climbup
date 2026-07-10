from typing import Any
from pydantic import BaseModel, Field

class AnswerVerificationRequest(BaseModel):
    question: str = Field(..., description="The original question")
    answer: Any = Field(..., description="The user's submitted answer (can be string or blocks)")

class AnswerVerificationResponse(BaseModel):
    is_valid: bool = Field(..., description="True if the answer is valid, false otherwise")
    reason: str = Field(..., description="Reason for validation or rejection")
