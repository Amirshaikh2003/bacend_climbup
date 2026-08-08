import json
import logging
import re
import concurrent.futures
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
        "Design the EXACT structure of a University Topper's Exam Answer to guarantee maximum marks. "
        "Break down the topic into 4 to 6 concise, perfectly logical sections. "
        "CRITICAL RULE: Prioritize diagrams WHERE RELEVANT! If the topic benefits from a visual representation (e.g., Recursion Tree, block diagrams, flowcharts), explicitly include a 'mermaid' or 'image' block. If a diagram is absolutely NOT important or makes no sense, do not force it.\n\n"
        "STRUCTURE MANDATE: Every answer MUST start with a strong 'Introduction' section and end with a solid 'Conclusion' section.\n"
        "For Numerical: I. Introduction -> II. Given Data -> III. Formulas -> IV. Step-by-step Calculation -> V. Final Result & Conclusion.\n"
        "For Derivations: I. Introduction -> II. Assumptions -> III. Diagram (image/mermaid) -> IV. Mathematical Steps -> V. Final Formula & Conclusion.\n"
        "For Math/Algorithms: I. Introduction -> II. Concept -> III. Recursion Tree / Flowchart (mermaid) -> IV. Step-by-step Solution -> V. Complexity Analysis & Conclusion.\n"
        "For TOC/Logic: I. Introduction -> II. Concept -> III. Transition Table -> IV. State Diagram (mermaid) -> V. Test Strings -> VI. Conclusion.\n"
        "For Differences: I. Detailed Introduction -> II. Comparison Table (Mandatory) -> III. Conclusion.\n"
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
def run_section_generator_agent(question: str, section: dict, full_rubric: list, image_url: str = None) -> list:
    """Agent 3 & 5: Generates content for ONE SPECIFIC section of the rubric."""
    from app.services.ai.gemini_client import chat_completion, chat_completion_with_images
    
    system_prompt = (
        "You are a University Exam Topper and an Expert Engineering Scholar writing ONE SPECIFIC SECTION of a final exam answer based on a strict rubric. "
        "Return an array of blocks exactly matching the frontend UI schema: "
        '{"type": "markdown"|"image"|"table"|"code"|"mermaid", "content": ... (or "data" for tables/images)}.\n'
        "CRITICAL GUIDELINES:\n"
        "- UNIVERSITY EXAM FORMAT: Write EXACTLY like a university topper. Use clear bullet points, bold key terms, and logically number your points. Ensure the tone is strictly academic. Focus ONLY on core concepts, necessary formulas, and key points to score maximum marks. Do not be overly verbose.\n"
        "- MATH & FORMULAS: Use LaTeX $...$ for inline math and $$...$$ for block math. ALWAYS bold or highlight the final answer/formula.\n"
        "- MULTIMODAL VISION-SYNC: If you are provided with an image, you MUST write your explanation by referring exactly to the labels, structural components, and variables shown in THIS specific image. Ensure total harmony between your text and the diagram.\n"
        "- TABLES: When type is 'table', 'data' MUST strictly be an object: {\"headers\": [\"H1\", \"H2\"], \"rows\": [[\"R1\", \"R2\"], ...]}. NEVER return 'None' or string for table data.\n"
        "- IMAGES: If the section asks for an 'image', return an 'image' block with 'title', 'query', and 'labels'. If a URL is already provided to you, you MUST include that exact URL in your image block output.\n"
        "- MERMAID: If the section asks for 'mermaid', return a 'mermaid' block with valid mermaid.js code.\n"
        "- OUTPUT: Only generate the content for the requested section. Do not generate the entire answer."
    )
    
    prompt = (
        f"Question: {question}\n\n"
        f"Full Answer Rubric (For Context Only):\n{json.dumps(full_rubric, indent=2)}\n\n"
        f"TARGET SECTION TO GENERATE NOW:\n{json.dumps(section, indent=2)}\n\n"
    )
    if image_url:
        prompt += f"PRE-FETCHED DIAGRAM URL: {image_url}\n(You MUST use this EXACT URL in your JSON output if returning an image block.)\n\n"
        
    prompt += "Generate the complete, highly-detailed content for THIS SECTION ONLY as a JSON array of blocks."
    
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        if image_url:
            res = chat_completion_with_images(messages, image_urls=[image_url], max_tokens=4096, temperature=0.3)
        else:
            res = chat_completion(messages, max_tokens=4096, temperature=0.3)
            
        blocks = json.loads(_extract_json(res))
        
        # Validation layer for tables (Empty Table Fix)
        for block in blocks:
            if block.get("type") == "table":
                data = block.get("data")
                if not isinstance(data, dict) or "headers" not in data or "rows" not in data:
                    logger.warning(f"Invalid table data detected: {data}. Converting to markdown.")
                    block["type"] = "markdown"
                    block["content"] = str(data)
                    
        return blocks
    except Exception as e:
        logger.error(f"Section Generator Agent failed: {e}\nRaw res: {locals().get('res', 'None')}")
        return [{"type": "markdown", "content": f"*(Content generation failed for this section)*"}]

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
                
            # Otherwise, try SerpAPI search or use pre-fetched URL
            url = block.get("url")
            if not url:
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
    
    # Step 3 & 5: Generate Content (Sequential to prevent 429)
    raw_blocks = []
    logger.info(f"[Agent 3] Starting sequential generation for {len(rubric)} sections...")
    
    from app.services.ai.Diagram_fetcher import _fetch_candidate_image_urls, _verify_image_with_vision
    
    future_to_index = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        for idx, section in enumerate(rubric):
            image_url = None
            # Pre-fetch image if the section requires one
            if section.get("content_type") == "image":
                query = str(section.get("query") or section.get("description") or "").strip()
                if len(query.split()) > 10:
                    query = " ".join(query.split()[:8])
                if query:
                    try:
                        logger.info(f"Pre-fetching image for query: {query}")
                        candidates = _fetch_candidate_image_urls(query)
                        image_url = _verify_image_with_vision(query, candidates)
                        if image_url:
                            section["pre_fetched_url"] = image_url
                            logger.info(f"Successfully pre-fetched: {image_url}")
                    except Exception as e:
                        logger.warning(f"Pre-fetch failed for {query}: {e}")
            
            future = executor.submit(run_section_generator_agent, question, section, rubric, image_url)
            future_to_index[future] = idx
            
        # Collect results in order
        section_results = [[] for _ in range(len(rubric))]
        for future in concurrent.futures.as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                section_blocks = future.result()
                section_results[idx] = section_blocks
            except Exception as e:
                logger.error(f"Section {idx} generated an exception: {e}")
                
        # Flatten the list of blocks
        for blocks in section_results:
            raw_blocks.extend(blocks)
            
    logger.info(f"[Agent 3] Generator combined {len(raw_blocks)} total blocks.")
    
    # Step 4: Visuals
    final_blocks = run_visual_agent(raw_blocks, classification, question)
    logger.info(f"[Agent 4] Visual Agent finished processing.")
    
    return {
        "answer": final_blocks,
        "blueprint": rubric,  # Provide rubric for debugging/UI info if needed
        "topics": [],
        "metadata": {"agentic_architecture": True, "classification": classification}
    }
