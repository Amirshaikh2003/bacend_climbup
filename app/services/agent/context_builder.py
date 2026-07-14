import json
from typing import Dict, Any

def build_context_prompt(db_data: Dict[str, Any], intent: str) -> str:
    """
    Formats the raw DB JSON data into a strict Markdown context block for the LLM.
    """
    if not db_data or "error" in db_data:
        return ""
        
    context_str = "\n\n=== FACTUAL DATABASE CONTEXT (STRICTLY ADHERE TO THIS) ===\n"
    context_str += "The following data is pulled directly from previous year question papers.\n"
    context_str += "DO NOT guess or invent statistics, frequencies, or marks. Use ONLY the data below.\n\n"
    
    if intent in ["QUESTION_FREQUENCY", "QUESTION_SEARCH", "MARKS_PATTERN", "QUESTION_EXPLANATION"]:
        topic = db_data.get("topic", "Unknown")
        freq = db_data.get("frequency", 0)
        avg_marks = db_data.get("average_marks", 0)
        
        context_str += f"**Topic/Keyword:** {topic}\n"
        context_str += f"**Appearance Frequency (PYQs):** {freq} times\n"
        context_str += f"**Average Marks Weightage:** {avg_marks} marks\n\n"
        
        samples = db_data.get("sample_questions", [])
        if samples:
            context_str += "**Sample Previous Questions:**\n"
            for idx, sq in enumerate(samples, 1):
                context_str += f"{idx}. \"{sq['question']}\" ({sq['marks']} Marks, Year: {sq['year']})\n"
        else:
            context_str += "No previous questions found for this topic.\n"
            
    elif intent == "IMPORTANT_TOPICS":
        topics = db_data.get("important_topics", [])
        if topics:
            context_str += "**High Weightage / Important Topics:**\n"
            for idx, t in enumerate(topics, 1):
                context_str += f"{idx}. {t['topic/module']} (Frequency: {t['frequency']}, Avg Marks: {t['avg_marks']})\n"
        else:
            context_str += "No important topics data available.\n"
            
    context_str += "========================================================\n\n"
    return context_str
