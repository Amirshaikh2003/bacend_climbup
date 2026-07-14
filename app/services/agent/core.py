import logging
from typing import List, Dict, Optional
from app.schemas.chat import ChatRequest
from app.services.agent.classifier import classify_intent
from app.services.agent.tools import search_topic_in_db, get_important_topics
from app.services.agent.context_builder import build_context_prompt
from app.services.ai.gemini_client import chat_completion_with_images
# If you want to use groq or openrouter, you can import them here and conditionally route
# from app.services.ai.groq_client import chat_completion as groq_chat_completion

logger = logging.getLogger(__name__)

def process_chat_request(request: ChatRequest, base_system_prompt: str) -> str:
    """
    The main orchestrator for the AI Agent.
    1. Classifies intent.
    2. Calls DB tools if necessary.
    3. Builds augmented prompt.
    4. Calls LLM.
    """
    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
    
    # 1. Intent Detection
    intent_data = classify_intent(messages_dict, request.context)
    intent = intent_data.get("intent", "GENERAL_CHAT")
    topic = intent_data.get("topic")
    
    logger.info(f"Agent classified intent: {intent}, topic: {topic}")
    
    # 2 & 3. Tool Selection & Context Building
    db_context_str = ""
    if intent in ["QUESTION_FREQUENCY", "QUESTION_SEARCH", "MARKS_PATTERN", "QUESTION_EXPLANATION", "EXAM_HISTORY"]:
        if topic:
            db_data = search_topic_in_db(topic)
            db_context_str = build_context_prompt(db_data, intent)
    elif intent == "IMPORTANT_TOPICS":
        db_data = get_important_topics()
        db_context_str = build_context_prompt(db_data, intent)
        
    # 4. Final Prompt Assembly
    final_system_prompt = base_system_prompt
    if db_context_str:
        final_system_prompt += db_context_str
        
    # Prepare messages array for the final AI Provider
    final_messages = [{"role": "system", "content": final_system_prompt}]
    final_messages.extend(messages_dict)
    
    image_urls = [request.image_url] if getattr(request, "image_url", None) else None

    # Route to Gemini (or Groq/OpenRouter if preferred for normal chats)
    try:
        reply = chat_completion_with_images(
            messages=final_messages,
            image_urls=image_urls,
            max_tokens=2048,
            temperature=0.4
        )
        return reply
    except Exception as api_err:
        logger.error(f"AI Provider failed in Agent Orchestrator: {api_err}")
        return "Our servers are currently experiencing high load. Please try again after some time. Thank you for your patience!"
