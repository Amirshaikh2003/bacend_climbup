import logging
from typing import Dict, Any
from app.services.ai.gemini_client import chat_completion
from app.services.ai.answer_generator import clean_json

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """\
You are an expert academic moderator for an engineering platform.
A student has submitted an answer to a specific question, and they want to make it public for other students to read.
Your job is to verify if this answer is appropriate to be published.

REJECTION CRITERIA (Set is_valid to false if ANY match):
1. OFF-TOPIC: The answer has nothing to do with the question.
2. NONSENSE/FUNNY: The answer contains jokes, random words, gibberish, spam, or unprofessional language.
3. INAPPROPRIATE: The answer contains harmful, offensive, or inappropriate content.
4. COMPLETELY WRONG: The answer is factually incorrect and misleading for the specific question. (Minor mistakes are okay, but completely misleading answers should be rejected).

ACCEPTANCE CRITERIA (Set is_valid to true):
- The answer is a genuine attempt to answer the question, is mostly factually correct, and uses professional language.

OUTPUT FORMAT:
You MUST return ONLY valid JSON in the following format. Do NOT output any markdown, code blocks, or text outside the JSON.
{{
  "is_valid": true/false,
  "reason": "A short, polite explanation of why it was accepted or rejected (to be shown to the user)."
}}

QUESTION:
{question}

STUDENT'S SUBMITTED ANSWER:
{answer}
"""

def verify_student_answer(question: str, answer: str) -> Dict[str, Any]:
    prompt = VERIFICATION_PROMPT.format(question=question, answer=answer)
    messages = [{"role": "user", "content": prompt}]
    
    try:
        raw_response = chat_completion(messages=messages, max_tokens=300, temperature=0.1)
        # Parse the JSON response securely using the existing utility
        parsed = clean_json(raw_response)
        
        is_valid = bool(parsed.get("is_valid", False))
        reason = str(parsed.get("reason", "Unknown reason"))
        
        return {
            "is_valid": is_valid,
            "reason": reason
        }
    except Exception as e:
        logger.error(f"Answer verification failed: {e}")
        # Fail open or fail closed? Let's fail safe (closed) and tell them to try again.
        return {
            "is_valid": False,
            "reason": "System verification failed due to high load. Please try submitting again later."
        }
