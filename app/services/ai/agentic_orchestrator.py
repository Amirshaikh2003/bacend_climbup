import json
import logging
import re
import concurrent.futures
from typing import Any, Dict, List

from app.services.ai.openrouter_client import chat_completion
from app.services.ai.Diagram_fetcher import get_image_link_from_serpapi
from app.services.ai.answer_generator import generate_mermaid_for_image

logger = logging.getLogger(__name__)

def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"): text = text[7:-3]
    elif text.startswith("```"): text = text[3:-3]
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return text
        
    json_str = match.group(1)
    # Fix invalid LaTeX escapes (e.g. \gamma -> \\gamma) without corrupting already double-escaped \\gamma
    json_str = re.sub(r'(?<!\\)\\(?![ntrbf\\"/])', r'\\\\', json_str)
    
    return json_str


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
    """Agent 2: Plans the answer structure (Topper Pedagogy)."""
    system_prompt = (
        "[SYSTEM]\n"
        "You are an Elite University Academic Architect. Your audience is a strict Engineering Evaluator.\n"
        "Your ONLY goal is to break the question into 4 to 6 logical sections that guarantee maximum marks.\n\n"
        "[RULES]\n"
        "1. MUST follow this structure: 1. Introduction (The Hook), 2-4. Core Technical Body, 5. Visual/Diagram Block (if relevant), 6. Conclusion (The Summary).\n"
        "2. MUST return ONLY a valid JSON array of section objects.\n"
        "3. Do NOT output any pleasantries or conversational text.\n"
        "4. Each section object MUST have: 'section_id', 'title', 'type' (markdown, table, image, mermaid), and 'instructions' (detailed generation rules).\n"
        "5. The 'instructions' MUST explicitly demand bullet points and keyword highlighting.\n"
        "6. Do NOT be overly verbose. Prioritize maximum marks in minimum sections.\n"
    )
    
    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "section_id": {"type": "INTEGER"},
                "section_name": {"type": "STRING"},
                "content_type": {"type": "STRING", "description": "markdown, table, image, mermaid, code, or math"},
                "instructions": {"type": "STRING", "description": "Detailed rules for content generation."}
            },
            "required": ["section_id", "section_name", "content_type", "instructions"]
        }
    }
    
    prompt = f"Question: {question}\nDomain: {classification['domain']}. Intent: {classification['intent']}.\nGenerate the structure now."
    
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
        return [{"section_name": "Answer", "content_type": "markdown", "instructions": "Write a detailed answer."}]

# -----------------------------------------------------------------------------
# Agent 3 & 5 Combined: Content Generator & Compiler
# -----------------------------------------------------------------------------
def run_section_generator_agent(question: str, section: dict, full_rubric: list, image_url: str = None) -> list:
    """Agent 3 & 5: Generates content for ONE SPECIFIC section (DeepSeek Topper)."""
    from app.services.ai.openrouter_client import chat_completion, chat_completion_with_images
    
    system_prompt = (
        "[SYSTEM]\n"
        "You are an Elite University Exam Topper and Expert Engineering Scholar. The audience is a strict Engineering Evaluator grading your paper.\n"
        "Do NOT output pleasantries. Do NOT hallucinate. Do NOT output markdown code block wrappers around the JSON array.\n\n"
        "[RULES]\n"
        "1. FORMAT: Return ONLY a valid JSON array of block objects. Each block MUST have 'type' (markdown/table/image/mermaid) and 'content' (for text) or 'data' (for table).\n"
        "2. BULLET POINTS ONLY: MUST convert all core explanations into clear, concise bullet points. Zero dense paragraphs allowed.\n"
        "3. ACTIVE HIGHLIGHTING: MUST aggressively **bold** every key technical term, variable, and formula so the evaluator sees them instantly.\n"
        "4. STRUCTURED NUMERICALS: For derivations or numericals, MUST use 'Given Data' -> 'Formulas' -> 'Step-by-step Calculation' -> 'Final Answer'.\n"
        "5. MATH RIGOR: MUST use double-escaped LaTeX `\\\\gamma` or `\\\\frac` for ALL math. This is a strict JSON parsing requirement.\n"
        "6. VERBOSITY PENALTY: Do not be overly verbose. Maximize information density and technical accuracy.\n"
        "7. TABLES: If type is 'table', 'data' MUST be an object: {\"headers\": [\"H1\"], \"rows\": [[\"R1\"]]}.\n"
        "8. MULTIMODAL SYNC: If an image URL is provided, MUST integrate its exact labels/variables into your explanation.\n"
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
        raw_output = locals().get('res', 'No output generated')
        logger.error(f"Section Generator Agent failed: {e}\nRaw res: {raw_output}")
        return [{"type": "markdown", "content": f"⚠️ **Format Error:** The AI generated the answer but failed to format it correctly. Here is the raw text:\n\n{raw_output}"}]

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
