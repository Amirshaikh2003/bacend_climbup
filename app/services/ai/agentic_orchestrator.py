import json
import logging
import re
from typing import Any, Dict, List

from app.services.ai.gemini_client import chat_completion
from app.services.ai.Diagram_fetcher import get_image_link_from_serpapi
from app.services.ai.answer_generator import generate_mermaid_for_image

logger = logging.getLogger(__name__)

def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"): text = text[7:-3]
    elif text.startswith("```"): text = text[3:-3]
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return match.group(1) if match else text


# -----------------------------------------------------------------------------
# Agent 1: The Classifier
# -----------------------------------------------------------------------------
def run_classifier_agent(question: str, user_context: str) -> dict:
    """Agent 1: Determines engineering domain, intent, and complexity."""
    system_prompt = (
        "You are an expert Engineering Professor Classifier. "
        "Analyze the given question and return a JSON object."
    )
    
    schema = {
        "type": "OBJECT",
        "properties": {
            "domain": {"type": "STRING", "description": "Specific engineering branch (e.g. Mechanical, TOC, DB, etc.)"},
            "intent": {
                "type": "STRING", 
                "description": "What the question asks for (e.g., Numerical, Derivation, Conceptual, Comparative, Design)"
            },
            "requires_diagram": {"type": "BOOLEAN", "description": "True if a diagram/flowchart/graph is essential for full marks."},
            "diagram_type_needed": {
                "type": "STRING", 
                "description": "'internet_search' if a standard real-world image (like OSI model or Lathe machine) works best, or 'custom_mermaid' if a logic-specific graph (like DFA or specific flowchart) is needed."
            }
        },
        "required": ["domain", "intent", "requires_diagram", "diagram_type_needed"]
    }
    
    prompt = f"Question: {question}\nUser Context: {user_context}"
    
    try:
        res = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=schema
        )
        return json.loads(_extract_json(res))
    except Exception as e:
        logger.error(f"Classifier Agent failed: {e}\nRaw res: {locals().get('res', 'None')}")
        return {"domain": "General Engineering", "intent": "Conceptual", "requires_diagram": False, "diagram_type_needed": "internet_search"}

# -----------------------------------------------------------------------------
# Agent 2: The Planner
# -----------------------------------------------------------------------------
def run_planner_agent(question: str, classification: dict) -> list:
    """Agent 2: Creates the grading rubric skeleton."""
    system_prompt = (
        "You are a strict University Examiner designing a marking rubric (skeleton) for an answer. "
        "Return an array of section objects. "
        f"Domain: {classification['domain']}. Intent: {classification['intent']}."
    )
    
    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "section_name": {"type": "STRING"},
                "content_type": {"type": "STRING", "description": "markdown, table, image, mermaid, code, or math"},
                "description": {"type": "STRING", "description": "Instructions for the writer agent on what exactly to include here."}
            },
            "required": ["section_name", "content_type", "description"]
        }
    }
    
    prompt = (
        f"Question: {question}\n\n"
        "Design the perfect answer structure to get maximum marks. "
        "For Numerical: Given Data -> Formulas -> Calculation -> Result.\n"
        "For Derivations: Assumptions -> Diagram -> Steps -> Final Formula.\n"
        "For TOC/Logic: Concept -> Transition Table -> State Diagram -> Test Strings.\n"
        "For Differences: Intro -> Table -> Conclusion.\n"
        "Output the array of sections."
    )
    
    try:
        res = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=schema
        )
        return json.loads(_extract_json(res))
    except Exception as e:
        logger.error(f"Planner Agent failed: {e}\nRaw res: {locals().get('res', 'None')}")
        return [{"section_name": "Answer", "content_type": "markdown", "description": "Write a detailed answer."}]

# -----------------------------------------------------------------------------
# Agent 3 & 5 Combined: Content Generator & Compiler
# -----------------------------------------------------------------------------
def run_generator_agent(question: str, rubric: list) -> list:
    """Agent 3 & 5: Fills the rubric with content and outputs final JSON blocks."""
    system_prompt = (
        "You are an expert Engineering Scholar writing a final exam answer based on a strict rubric. "
        "Return an array of blocks exactly matching the frontend UI schema: "
        '{"type": "markdown"|"image"|"table"|"code"|"mermaid", "content": ... (or "data" for tables/images)}.\n'
        "Guidelines:\n"
        "- Use markdown for text/math. Bold important keywords. Use LaTeX $...$ or $$...$$ for math.\n"
        "- Use 'table' type with 'data' matrix for tabular comparisons.\n"
        "- If a rubric section asks for an 'image', return an 'image' block with 'title', 'query', and 'labels'.\n"
        "- If a rubric section asks for 'mermaid', return a 'mermaid' block with valid mermaid.js code.\n"
    )
    
    prompt = f"Question: {question}\n\nRubric Skeleton:\n{json.dumps(rubric, indent=2)}\n\nGenerate the complete answer as a JSON array of blocks."
    
    try:
        res = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=8192,
            temperature=0.4
        )
        return json.loads(_extract_json(res))
    except Exception as e:
        logger.error(f"Generator Agent failed: {e}\nRaw res: {locals().get('res', 'None')}")
        return [{"type": "markdown", "content": f"**Error generating advanced answer.**\nPlease try again."}]

# -----------------------------------------------------------------------------
# Agent 4: The Art Director (Visual Enrichment)
# -----------------------------------------------------------------------------
def run_visual_agent(blocks: list, classification: dict, question: str) -> list:
    """Agent 4: Processes image and mermaid blocks."""
    updated_blocks = []
    
    for block in blocks:
        if block.get("type") == "image":
            # If classifier says we need custom mermaid, force fallback immediately
            if classification.get("diagram_type_needed") == "custom_mermaid":
                fallback = generate_mermaid_for_image(block, question)
                updated_blocks.append(fallback if fallback else block)
                continue
                
            # Otherwise, try SerpAPI search
            url = None
            try:
                # Add recommended websites for SerpApi precision
                block["recommended_website"] = "GeeksforGeeks, Wikipedia"
                url = get_image_link_from_serpapi(block)
            except Exception as e:
                logger.warning(f"Image fetch failed: {e}")
                
            if url:
                block["url"] = url
                updated_blocks.append(block)
            else:
                # Intelligent fallback
                fallback = generate_mermaid_for_image(block, question)
                updated_blocks.append(fallback if fallback else block)
        else:
            updated_blocks.append(block)
            
    return updated_blocks

# -----------------------------------------------------------------------------
# Main Orchestrator
# -----------------------------------------------------------------------------
def generate_agentic_answer(question: str, user_context: str = "") -> dict:
    """The master pipeline combining all 5 agents."""
    
    logger.info("--- Starting Multi-Agent Pipeline ---")
    
    # Step 1: Classify
    classification = run_classifier_agent(question, user_context)
    logger.info(f"[Agent 1] Classifier Output: {classification}")
    
    # Step 2: Plan
    rubric = run_planner_agent(question, classification)
    logger.info(f"[Agent 2] Planner Output: {rubric}")
    
    # Step 3 & 5: Generate Content
    raw_blocks = run_generator_agent(question, rubric)
    logger.info(f"[Agent 3] Generator created {len(raw_blocks)} blocks.")
    
    # Step 4: Visuals
    final_blocks = run_visual_agent(raw_blocks, classification, question)
    logger.info(f"[Agent 4] Visual Agent finished processing.")
    
    return {
        "answer": final_blocks,
        "blueprint": rubric,  # Provide rubric for debugging/UI info if needed
        "topics": [],
        "metadata": {"agentic_architecture": True, "classification": classification}
    }
