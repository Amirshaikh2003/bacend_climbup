import json
import logging
from typing import Dict, Any, List
from app.services.ai.gemini_client import chat_completion_with_images

logger = logging.getLogger(__name__)

INTENT_PROMPT = """You are an Intent Classification AI for an engineering student chatbot.
Your job is to analyze the user's latest message (in the context of the conversation) and determine their intent.

Available Intents:
1. QUESTION_FREQUENCY: The user wants to know how many times a topic/question was asked in previous exams (PYQs), or which year it appeared.
2. QUESTION_SEARCH: The user is searching for previous year questions on a specific topic.
3. IMPORTANT_TOPICS: The user wants to know the most important topics or high-weightage topics for a subject.
4. MARKS_PATTERN: The user wants to know the marks distribution or average marks for a topic/question.
5. EXAM_HISTORY: The user wants to know general history about a paper or topic.
6. QUESTION_EXPLANATION: The user wants an explanation, solution, or definition for a specific academic concept/question.
7. GENERAL_CHAT: The user is just saying hello, asking general non-academic questions, or the query doesn't fit above.

You MUST respond ONLY with a valid JSON object in the exact format below, with NO markdown formatting or extra text:
{
    "intent": "ONE_OF_THE_INTENTS",
    "topic": "extracted_topic_or_entity_name_if_applicable_else_null"
}
If a context is provided below, assume the user's query refers to that context if they use words like "this", "it", or ask a question without specifying the topic.

"""

def classify_intent(messages: List[Dict[str, str]], context: str = None) -> Dict[str, Any]:
    """
    Classifies the user's intent using Gemini.
    """
    try:
        prompt = INTENT_PROMPT
        if context:
            prompt += f"\n\nCURRENT ACTIVE CONTEXT/QUESTION:\n\"{context}\"\n"
            
        # Prepare messages just for classification
        classifier_messages = [{"role": "system", "content": prompt}]
        
        # We only need the last few messages for context to keep it fast
        recent_messages = messages[-3:]
        classifier_messages.extend(recent_messages)
        
        # Call Gemini (we want a fast response, so low max_tokens and low temperature)
        reply = chat_completion_with_images(
            messages=classifier_messages,
            image_urls=None,
            max_tokens=150,
            temperature=0.1
        )
        
        # Clean the reply (strip markdown json blocks if any)
        reply = reply.strip()
        if reply.startswith("```json"):
            reply = reply[7:]
        if reply.endswith("```"):
            reply = reply[:-3]
            
        result = json.loads(reply.strip())
        return result
    except Exception as e:
        logger.error(f"Intent classification failed: {e}")
        # Default fallback
        return {"intent": "GENERAL_CHAT", "topic": None}
