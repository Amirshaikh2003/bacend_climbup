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
                exam_info = sq.get('exam_info', sq.get('year', 'Unknown'))
                context_str += f"{idx}. \"{sq['question']}\" ({sq['marks']} Marks, Exam: {exam_info})\n"
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
            
    elif intent == "TOP_STUDENT_ANSWERS":
        topic = db_data.get("topic", "Unknown")
        answers = db_data.get("top_student_answers", [])
        msg = db_data.get("message")
        
        context_str += f"**Topic/Keyword:** {topic}\n\n"
        if msg:
            context_str += f"{msg}\n"
        elif answers:
            context_str += "**Top Student Answers (Present these to the user!):**\n"
            for idx, ans in enumerate(answers, 1):
                context_str += f"--- Answer {idx} ---\n"
                context_str += f"Question context: {ans.get('question', 'Unknown')}\n"
                context_str += f"Author: {ans.get('author_name', 'Anonymous')} (Reputation: {ans.get('author_reputation', 0)})\n"
                context_str += f"Score: {ans.get('verification_score', 0)}/100, Likes: {ans.get('likes_count', 0)}\n"
                context_str += f"Answer: {ans.get('answer_content', '')}\n\n"

    context_str += "========================================================\n\n"
    return context_str
