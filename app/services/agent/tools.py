import logging
import urllib.parse
from typing import Dict, Any, List
from app.services.supabase_service import _session, SUPABASE_URL, SUPABASE_KEY, _require_config

logger = logging.getLogger(__name__)

def _db_get(table: str, params: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """Helper to query supabase via REST API."""
    _require_config()
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    }
    
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if params:
        # urlencode params
        query_string = urllib.parse.urlencode(params, safe="=,&")
        url = f"{url}?{query_string}"
    else:
        url = f"{url}?select=*"

    try:
        response = _session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"DB GET failed for {url}: {e}")
        return []

def search_topic_in_db(topic: str) -> Dict[str, Any]:
    """
    Find questions related to a specific topic by doing an ilike search on question_text or module.
    Returns frequency and list of questions with their marks and year.
    """
    if not topic:
        return {"error": "No topic provided"}
        
    logger.info(f"Agent Tool: Searching DB for topic: {topic}")
    
    # We will search the questions table joined with question_papers to get the year.
    # PostgREST supports embedded resources.
    # Query: questions?select=question_text,marks,difficulty,question_papers(year,exam_type)&question_text=ilike.*topic*
    
    params = {
        "select": "question_text,marks,difficulty,question_papers(year,exam_type,paper_title)",
        "question_text": f"ilike.*{topic}*",
        "order": "marks.desc"
    }
    
    results = _db_get("questions", params)
    
    if not results:
        # Try searching by module name if no text match
        params = {
            "select": "question_text,marks,difficulty,question_papers(year,exam_type,paper_title)",
            "module": f"ilike.*{topic}*",
            "order": "marks.desc"
        }
        results = _db_get("questions", params)
    
    if not results:
        return {"message": f"No previous questions found for topic: {topic}", "frequency": 0}
        
    frequency = len(results)
    avg_marks = sum(r.get("marks", 0) for r in results) / frequency if frequency > 0 else 0
    
    # Format the data for the LLM
    formatted_questions = []
    for r in results[:10]: # Limit to top 10 to avoid massive context
        paper = r.get("question_papers") or {}
        year = paper.get("year", "Unknown")
        exam = paper.get("exam_type", "Unknown")
        title = paper.get("paper_title", "")
        
        display_exam = title if title else f"{exam} {year}"
        
        formatted_questions.append({
            "question": r.get("question_text"),
            "marks": r.get("marks"),
            "year": year,
            "exam_info": display_exam
        })
        
    return {
        "topic": topic,
        "frequency": frequency,
        "average_marks": round(avg_marks, 2),
        "sample_questions": formatted_questions
    }

def get_important_topics() -> Dict[str, Any]:
    """
    Fetches topics with highest frequency/marks.
    For now, we'll fetch questions with highest marks and most occurrences.
    """
    params = {
        "select": "module,marks,question_papers(year)",
        "order": "marks.desc",
        "limit": "20"
    }
    results = _db_get("questions", params)
    
    # aggregate by module
    module_stats = {}
    for r in results:
        mod = r.get("module") or "General"
        if mod not in module_stats:
            module_stats[mod] = {"count": 0, "total_marks": 0}
        module_stats[mod]["count"] += 1
        module_stats[mod]["total_marks"] += r.get("marks", 0)
        
    important = []
    for mod, stats in module_stats.items():
        important.append({
            "topic/module": mod,
            "frequency": stats["count"],
            "avg_marks": round(stats["total_marks"] / stats["count"], 1)
        })
        
    # Sort by frequency
    important.sort(key=lambda x: x["frequency"], reverse=True)
    
    return {
        "important_topics": important[:5]
    }

def get_top_student_answers(topic: str) -> Dict[str, Any]:
    """
    Fetches the highest-rated student answers for questions related to the topic.
    """
    if not topic:
        return {"error": "No topic provided"}
        
    logger.info(f"Agent Tool: Searching for top student answers for topic: {topic}")
    
    # 1. First, find questions matching the topic
    params = {
        "select": "question_id,question_text,marks",
        "question_text": f"ilike.*{topic}*",
        "limit": "5"
    }
    
    questions = _db_get("questions", params)
    if not questions:
        # Try searching by module
        params = {
            "select": "question_id,question_text,marks",
            "module": f"ilike.*{topic}*",
            "limit": "5"
        }
        questions = _db_get("questions", params)
        
    if not questions:
        return {"message": f"No questions found for topic: {topic}"}
        
    # 2. For the found questions, fetch top student answers
    question_ids = [str(q.get("question_id")) for q in questions if q.get("question_id")]
    if not question_ids:
        return {"message": "Could not extract question IDs."}
        
    id_list_str = ",".join(question_ids)
    
    ans_params = {
        "select": "answer_content,verification_score,likes_count,status,question_id,users(full_name,reputation)",
        "question_id": f"in.({id_list_str})",
        "status": "eq.published",
        "order": "verification_score.desc,likes_count.desc",
        "limit": "5"
    }
    
    answers = _db_get("student_answers", ans_params)
    
    if not answers:
        return {"message": "No published student answers found for this topic yet. Be the first to answer!"}
        
    # Match answers back to their questions for better context
    formatted_results = []
    for ans in answers:
        q_id = ans.get("question_id")
        q_text = next((q["question_text"] for q in questions if q.get("question_id") == q_id), "Unknown Question")
        user_info = ans.get("users", {}) or {}
        
        formatted_results.append({
            "question": q_text,
            "answer_content": ans.get("answer_content", ""),
            "verification_score": ans.get("verification_score", 0),
            "likes_count": ans.get("likes_count", 0),
            "author_name": user_info.get("full_name", "Anonymous"),
            "author_reputation": user_info.get("reputation", 0)
        })
        
    return {
        "topic": topic,
        "top_student_answers": formatted_results
    }
