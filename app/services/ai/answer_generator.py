import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.ai.openrouter_client import chat_completion
from app.services.ai.Diagram_fetcher import get_image_link_from_serpapi

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_BLOCK_TYPES = frozenset(
    {"markdown", "image", "table", "steps", "mermaid", "code"}
)

SUPPORTED_MERMAID_TYPES = frozenset(
    {"flowchart", "sequence", "class", "state", "er", "journey", "gantt", "pie", "mindmap"}
)

DEFAULT_RECOMMENDED_WEBSITES = ["GeeksforGeeks", "Wikipedia"]

VISUAL_KEYWORDS = frozenset({
    "osi", "tcp", "ip", "architecture", "model", "layer", "layers",
    "flowchart", "algorithm", "process", "working", "block diagram",
    "diagram", "network", "system", "lifecycle", "data flow", "memory",
    "cpu", "database", "cloud", "organization", "circuit", "component",
    "pipeline", "topology", "uml", "er diagram", "class diagram",
    "sequence diagram", "pll", "phase locked loop", "control unit",
    "memory hierarchy", "compiler", "software engineering",
    "machine learning", "data structure", "dbms", "operating system",
})


MANDATORY_VISUAL_TOPIC_RULES = (
    {
        "topic_any": ("machine learning", "ml"),
        "question_any": ("steps", "process", "workflow", "lifecycle", "life cycle", "pipeline", "working"),
        "title": "Machine Learning Workflow Diagram",
        "visual_type": "Machine Learning workflow / lifecycle diagram",
        "diagram_labels": [
            "Data collection",
            "Data preprocessing",
            "Feature extraction / selection",
            "Model training",
            "Model testing / validation",
            "Model evaluation",
            "Deployment",
            "Feedback / improvement",
        ],
        "image_search_query": "machine learning workflow lifecycle steps diagram",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
    },
    {
        "topic_any": ("software development life cycle", "sdlc"),
        "question_any": ("steps", "phases", "process", "lifecycle", "life cycle"),
        "title": "SDLC Phases Diagram",
        "visual_type": "SDLC phases diagram",
        "diagram_labels": ["Planning", "Analysis", "Design", "Implementation", "Testing", "Deployment", "Maintenance"],
        "image_search_query": "SDLC phases lifecycle diagram",
        "recommended_websites": ["GeeksforGeeks", "Tutorialspoint"],
    },
    {
        "topic_any": ("compiler",),
        "question_any": ("phases", "passes", "working", "process", "structure"),
        "title": "Compiler Phases Diagram",
        "visual_type": "Compiler phases diagram",
        "diagram_labels": ["Lexical analysis", "Syntax analysis", "Semantic analysis", "Intermediate code", "Optimization", "Code generation"],
        "image_search_query": "compiler phases labelled diagram",
        "recommended_websites": ["GeeksforGeeks", "Tutorialspoint"],
    },
    {
        "topic_any": ("instruction cycle", "fetch decode execute"),
        "question_any": ("steps", "working", "cycle", "process"),
        "title": "Instruction Cycle Flow Diagram",
        "visual_type": "Instruction cycle flow diagram",
        "diagram_labels": ["Fetch", "Decode", "Execute", "Memory access", "Write back", "Next instruction"],
        "image_search_query": "instruction cycle fetch decode execute flow diagram",
        "recommended_websites": ["GeeksforGeeks", "Wikipedia"],
    },
    {
        "topic_any": ("osi", "tcp/ip", "tcp ip"),
        "question_any": ("model", "layers", "architecture", "explain"),
        "title": "Layered Network Model Diagram",
        "visual_type": "Layered network model diagram",
        "diagram_labels": ["Application", "Transport", "Network", "Data Link", "Physical"],
        "image_search_query": "OSI TCP IP layered model diagram",
        "recommended_websites": ["GeeksforGeeks", "Cisco"],
    },
)

# Recommended visuals are not mandatory, but they can make ML/Data Science
# comparison answers clearer. They should be inserted only when the analyzer
# marks visual_priority as recommended or this heuristic matches.
RECOMMENDED_VISUAL_TOPIC_RULES = (
    {
        "topic_any": ("classification", "regression"),
        "question_any": ("compare", "comparison", "differentiate", "distinguish", "difference", " vs ", "versus"),
        "title": "Classification vs Regression Visual Comparison",
        "visual_type": "conceptual visual comparison",
        "diagram_labels": [
            "Supervised Learning",
            "Classification",
            "Regression",
            "Discrete / class output",
            "Continuous numeric output",
            "Example",
        ],
        "image_search_query": "classification vs regression machine learning visual example",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
    },
    {
        "topic_any": ("supervised learning", "unsupervised learning"),
        "question_any": ("compare", "comparison", "differentiate", "distinguish", "difference", " vs ", "versus"),
        "title": "Supervised vs Unsupervised Learning Visual Comparison",
        "visual_type": "conceptual visual comparison",
        "diagram_labels": ["Machine Learning", "Supervised Learning", "Unsupervised Learning", "Labeled Data", "Unlabeled Data", "Example"],
        "image_search_query": "supervised vs unsupervised learning visual comparison",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
    },
    {
        "topic_any": ("classification", "clustering"),
        "question_any": ("compare", "comparison", "differentiate", "distinguish", "difference", " vs ", "versus"),
        "title": "Classification vs Clustering Visual Comparison",
        "visual_type": "conceptual visual comparison",
        "diagram_labels": ["Machine Learning", "Classification", "Clustering", "Known Classes", "Discovered Groups", "Example"],
        "image_search_query": "classification vs clustering visual comparison machine learning",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
    },
)


MAX_TOKENS = 16000


# ─────────────────────────────────────────────────────────────────────────────
# Marks → Word Targets
# ─────────────────────────────────────────────────────────────────────────────

MARKS_SCALE: List[Tuple[int, int, int]] = [
    # marks threshold, minimum words, target words
    (15, 2200, 2800),
    (12, 1700, 2100),
    (10, 1300, 1700),
    (8, 1000, 1350),
    (6, 650, 900),
    (4, 380, 500),
    (2, 180, 250),
]


def get_word_targets(marks: int) -> Tuple[int, int]:
    for threshold, min_words, target_words in MARKS_SCALE:
        if marks >= threshold:
            return min_words, target_words
    return 180, 250


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

BASE_JSON_RULES = """\
You are a senior Engineering professor & exam evaluator across ALL branches (CSE, IT, Mech, Civil, Electrical, etc.).
STRICT OUTPUT RULES:
1. Return ONLY valid JSON format: {{"question": "str", "answer": [blocks]}}.
2. Blocks allowed: markdown, image, table, steps, mermaid, code. NO other blocks.
3. Every block must strictly follow its JSON schema.
4. Images and mermaid blocks are OPTIONAL. Only use them if they heavily enhance the answer (e.g. system architectures, circuit diagrams, flowcharts). Do not use them for pure theory or math.
5. Do NOT output any text outside the JSON. Do not stop mid-sentence.
"""

SPECIALIST_RULES = {
    "comparison": "COMPARISON MODE: Must be table-dominant (Parameter, Concept 1, Concept 2). Short intro. 6-10 rows based on marks. No history unless asked.",
    "process": "PROCESS MODE: Use 'steps' block. Detail each stage's cause/action/result. Add a 'mermaid' flowchart if it clarifies the process.",
    "hierarchy": "HIERARCHY MODE: Explain each layer/level clearly in markdown or table. Add an 'image' block if an architecture diagram is critical.",
    "calculation": "NUMERICAL MODE: Use 'steps' block. Show Given Data -> Formula -> Step-by-Step Substitution -> Final Answer with units. No images.",
    "code": "CODE MODE: Use 'code' block. Include complete syntax & output. Use 'steps' or 'mermaid' for algorithm explanation if requested.",
    "image": "VISUAL MODE: Use 'image' block for educational/architecture diagrams. Use 'mermaid' for logical flowcharts.",
    "text": "THEORY MODE: Use 'markdown'. For Applications/Advantages/Disadvantages use bullet points. Give technical reasons."
}

def select_system_prompt(analysis: dict, question: str = "") -> str:
    ans_type = (analysis.get("answer_type") or "text").lower()
    if ans_type not in SPECIALIST_RULES:
        ans_type = "text"
        
    rule = SPECIALIST_RULES[ans_type]
    return f"{BASE_JSON_RULES}\n\n{rule}"

ANSWER_PROMPT_TEMPLATE = """\
Write a deeply detailed university exam model answer for this {marks}-mark BE/BTech question.
Return ONLY valid JSON: {{"question": "string", "answer": []}}

LENGTH & QUALITY:
- Write at least {min_words} words (target {target_words}+).
- Fully expand theory, components, and applications.
- For 6+ marks, give 5+ concise bullet points for Advantages/Applications.

ANALYZER RULES:
Follow the provided ANALYZER for depth, blocks, and focus.
- Only include an 'image' or 'mermaid' block if a diagram is GENUINELY REQUIRED or heavily enhances the answer (e.g., architecture, flowchart). Do NOT use them for purely mathematical, theoretical, or code questions.

BLOCK SCHEMAS (DO NOT DEVIATE):
1. markdown: {{"type": "markdown", "title": "str", "content": "str"}} (Use ## headings, bold **terms**. No code/tables inside).
2. image: {{"type": "image", "title": "str", "search_query": "str", "recommended_websites": ["site"]}}
3. table: {{"type": "table", "title": "str", "columns": ["c1", "c2"], "rows": [["v1", "v2"]]}} (Rows must match columns count).
4. steps: {{"type": "steps", "title": "str", "items": [{{"step": 1, "content": "str"}}]}}
5. mermaid: {{"type": "mermaid", "title": "str", "diagram_type": "flowchart", "content": "valid syntax"}}
6. code: {{"type": "code", "title": "str", "language": "str", "content": "code", "explanation": ["str"], "output": "str"}}

DYNAMIC STRUCTURE:
Do NOT use a single rigid format. Dynamically structure your answer based on the subject and question type (e.g., Mathematical proofs need formulas/steps, CS needs code/architecture, Civil/Mech needs theory/diagrams). Arrange blocks logically for the highest exam score.

CRITICAL: Return ONLY JSON.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUESTION : {question}
MARKS    : {marks}
ANALYZER : {analysis_json}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ─────────────────────────────────────────────────────────────────────────────
# Generic Helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_analysis(analysis: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return analysis if isinstance(analysis, dict) else {}


def coerce_string(value: Any) -> str:
    return str(value or "").strip()


def coerce_string_list(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    if fallback is None:
        fallback = []

    if isinstance(value, list):
        items = [coerce_string(item) for item in value]
        return [item for item in items if item]

    if isinstance(value, str):
        if "," in value:
            items = [item.strip() for item in value.split(",")]
            return [item for item in items if item]
        return [value.strip()] if value.strip() else fallback

    return fallback


def restore_text_line_escapes(content: str) -> str:
    return content.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


# ─────────────────────────────────────────────────────────────────────────────
# JSON Cleaning / Repair
# ─────────────────────────────────────────────────────────────────────────────

def clean_json(raw: str) -> Dict[str, Any]:
    if not raw:
        raise ValueError("Empty AI response")

    text = raw.strip()

    if "<think>" in text:
        end = text.find("</think>")
        text = text[end + 8:].strip() if end != -1 else text

    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):].strip()
            break

    if text.endswith("```"):
        text = text[:-3].strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in AI response")

    json_text = text[start:end + 1]
    repaired = repair_json_string_escapes(json_text)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as repaired_error:
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            raise repaired_error


def repair_json_string_escapes(text: str) -> str:
    """
    Repairs common invalid JSON escapes inside quoted strings.

    LLMs may output code, regex, or LaTeX-like text with single backslashes.
    This function repairs invalid escapes while preserving valid JSON structure.
    """
    output: List[str] = []
    in_string = False
    escaped = False
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
    i = 0

    while i < len(text):
        char = text[i]

        if not in_string:
            output.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue

        if escaped:
            next_char = text[i + 1] if i + 1 < len(text) else ""
            looks_like_command = char.isalpha() and next_char.isalpha()

            if char not in valid_escapes or looks_like_command:
                output.append("\\")

            output.append(char)
            escaped = False
            i += 1
            continue

        if char == "\\":
            output.append(char)
            escaped = True
            i += 1
            continue

        if char == '"':
            in_string = False
            output.append(char)
            i += 1
            continue

        if char == "\n":
            output.append("\\n")
        elif char == "\r":
            output.append("\\r")
        elif char == "\t":
            output.append("\\t")
        else:
            output.append(char)

        i += 1

    if escaped:
        output.append("\\")

    return "".join(output)


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter Helpers
# ─────────────────────────────────────────────────────────────────────────────

def openrouter_call(
    messages: List[Dict[str, str]],
    model: str | None = None,
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0.25,
) -> str:
    return chat_completion(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def build_prompt(question: str, analysis: Dict[str, Any], marks: int) -> str:
    min_words, target_words = get_word_targets(marks)

    return ANSWER_PROMPT_TEMPLATE.format(
        question=question,
        marks=marks,
        min_words=min_words,
        target_words=target_words,
        analysis_json=json.dumps(analysis, indent=2, ensure_ascii=False),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Block Validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_blocks(blocks: Any, question: str) -> List[Dict[str, Any]]:
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("answer must be a non-empty list")

    validated_blocks: List[Dict[str, Any]] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        block_type = coerce_string(block.get("type")).lower()

        if block_type not in SUPPORTED_BLOCK_TYPES:
            continue

        if block_type == "markdown":
            validated = validate_markdown_block(block)
        elif block_type == "image":
            validated = validate_image_block(block, question)
        elif block_type == "table":
            validated = validate_table_block(block)
        elif block_type == "steps":
            validated = validate_steps_block(block)
        elif block_type == "mermaid":
            validated = validate_mermaid_block(block)
        elif block_type == "code":
            validated = validate_code_block(block)
        else:
            validated = None

        if validated:
            validated_blocks.append(validated)

    if not validated_blocks:
        raise ValueError("No valid answer blocks found")

    if not any(block["type"] == "markdown" for block in validated_blocks):
        validated_blocks.insert(0, {
            "type": "markdown",
            "title": "Introduction",
            "content": (
                "## Introduction\n\n"
                f"{question} is an important engineering topic. "
                "The following answer presents it in a structured university-exam format."
            ),
        })

    return validated_blocks


def validate_markdown_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or "Explanation"
    content = restore_text_line_escapes(coerce_string(block.get("content")))

    if not content:
        return None

    return {
        "type": "markdown",
        "title": title,
        "content": content,
    }


def validate_image_block(block: Dict[str, Any], question: str) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or f"{question} Diagram"
    search_query = (
        coerce_string(block.get("search_query"))
        or f"{question} detailed labelled educational diagram"
    )

    recommended_websites = coerce_string_list(
        block.get("recommended_websites"),
        fallback=[],
    )

    # Backward compatibility with older prompt/output.
    if not recommended_websites:
        recommended_websites = coerce_string_list(
            block.get("recommended_website"),
            fallback=DEFAULT_RECOMMENDED_WEBSITES,
        )

    recommended_websites = recommended_websites[:2] or DEFAULT_RECOMMENDED_WEBSITES

    validated: Dict[str, Any] = {
        "type": "image",
        "title": title,
        "search_query": search_query,
        "recommended_websites": recommended_websites,
    }

    url = coerce_string(block.get("url"))
    if url:
        validated["url"] = url

    return validated


def validate_table_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or "Table"

    columns = block.get("columns")

    # Backward compatibility with older output.
    if not isinstance(columns, list):
        columns = block.get("headers")

    rows = block.get("rows")

    if not isinstance(columns, list) or not columns:
        return None

    if not isinstance(rows, list) or not rows:
        return None

    clean_columns = [coerce_string(column) for column in columns]

    if not all(clean_columns):
        return None

    clean_rows: List[List[str]] = []

    for row in rows:
        if not isinstance(row, list):
            continue

        if len(row) != len(clean_columns):
            continue

        clean_rows.append([coerce_string(cell) for cell in row])

    if not clean_rows:
        return None

    return {
        "type": "table",
        "title": title,
        "columns": clean_columns,
        "rows": clean_rows,
    }


def validate_steps_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or "Step-by-Step Explanation"
    items = block.get("items")

    if not isinstance(items, list) or not items:
        return None

    clean_items: List[Dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            step_number = item.get("step", index)
            content = restore_text_line_escapes(coerce_string(item.get("content")))
        else:
            step_number = index
            content = restore_text_line_escapes(coerce_string(item))

        if not content:
            continue

        try:
            step_number = int(step_number)
        except (TypeError, ValueError):
            step_number = index

        clean_items.append({
            "step": step_number,
            "content": content,
        })

    if not clean_items:
        return None

    return {
        "type": "steps",
        "title": title,
        "items": clean_items,
    }


def validate_mermaid_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or "Diagram"
    diagram_type = coerce_string(block.get("diagram_type")).lower()
    content = restore_text_line_escapes(coerce_string(block.get("content")))

    # Backward compatibility with older output.
    if not content:
        content = restore_text_line_escapes(coerce_string(block.get("code")))

    if not content:
        return None

    if not diagram_type:
        diagram_type = infer_mermaid_type(content)

    if diagram_type not in SUPPORTED_MERMAID_TYPES:
        diagram_type = "flowchart"

    return {
        "type": "mermaid",
        "title": title,
        "diagram_type": diagram_type,
        "content": content,
    }


def validate_code_block(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = coerce_string(block.get("title")) or "Code"
    language = coerce_string(block.get("language")) or "text"
    content = restore_text_line_escapes(coerce_string(block.get("content")))
    explanation = block.get("explanation", [])
    output = restore_text_line_escapes(coerce_string(block.get("output")))

    if not content:
        return None

    if not isinstance(explanation, list):
        explanation = [coerce_string(explanation)]

    explanation = [
        coerce_string(item)
        for item in explanation
        if coerce_string(item)
    ]

    return {
        "type": "code",
        "title": title,
        "language": language,
        "content": content,
        "explanation": explanation,
        "output": output,
    }


def infer_mermaid_type(content: str) -> str:
    lowered = content.strip().lower()

    if lowered.startswith("sequencediagram"):
        return "sequence"

    if lowered.startswith("classdiagram"):
        return "class"

    if lowered.startswith("statediagram"):
        return "state"

    if lowered.startswith("erdiagram"):
        return "er"

    if lowered.startswith("journey"):
        return "journey"

    if lowered.startswith("gantt"):
        return "gantt"

    if lowered.startswith("pie"):
        return "pie"

    if lowered.startswith("mindmap"):
        return "mindmap"

    return "flowchart"


def validate_output(data: Dict[str, Any], question: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("AI response is not a JSON object")

    return {
        "question": coerce_string(data.get("question")) or question,
        "answer": validate_blocks(data.get("answer"), question),
    }



# ─────────────────────────────────────────────────────────────────────────────
# Quality Post-Processing
# ─────────────────────────────────────────────────────────────────────────────

COMPARISON_TRIGGERS = frozenset({
    "compare", "comparison", "differentiate", "distinguish", "difference between",
    "versus", " vs ", "merits and demerits", "advantages and disadvantages",
})

UNWANTED_SECTION_KEYWORDS_BY_TYPE: Dict[str, frozenset[str]] = {
    "comparison": frozenset({"history", "evolution", "future scope", "background"}),
}

EXPLICIT_SECTION_KEYWORDS = frozenset({
    "history", "evolution", "future scope", "background", "origin", "development"
})


def get_analysis_answer_type(analysis: Dict[str, Any], question: str = "") -> str:
    """Returns normalized answer_type, with a safe fallback from question text."""
    answer_type = coerce_string(analysis.get("answer_type")).lower()

    if answer_type:
        return answer_type

    lowered_question = f" {question.lower()} "
    if any(trigger in lowered_question for trigger in COMPARISON_TRIGGERS):
        return "comparison"

    return "text"


def question_explicitly_asks(question: str, keyword: str) -> bool:
    return keyword.lower() in question.lower()


def min_comparison_rows(marks: int) -> int:
    if marks >= 12:
        return 10
    if marks >= 8:
        return 8
    return 6


def strip_unwanted_markdown_sections(content: str, answer_type: str, question: str) -> str:
    """
    Removes sections like History/Future Scope from markdown when the question did not ask.
    This prevents comparison answers from becoming bulky and irrelevant.
    """
    unwanted = UNWANTED_SECTION_KEYWORDS_BY_TYPE.get(answer_type, frozenset())
    if not unwanted or not content:
        return content

    # Keep the content untouched if the question explicitly asks for the section.
    if any(question_explicitly_asks(question, keyword) for keyword in EXPLICIT_SECTION_KEYWORDS):
        return content

    lines = content.splitlines()
    kept_lines: List[str] = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        is_heading = stripped.startswith("#")

        if is_heading:
            heading_text = stripped.lstrip("#").strip().lower()
            skipping = any(keyword in heading_text for keyword in unwanted)

        if not skipping:
            kept_lines.append(line)

    cleaned = "\n".join(kept_lines).strip()
    return cleaned or content


def remove_unwanted_blocks(
    blocks: List[Dict[str, Any]],
    answer_type: str,
    question: str,
) -> List[Dict[str, Any]]:
    """Removes entire irrelevant blocks and cleans irrelevant markdown subsections."""
    unwanted = UNWANTED_SECTION_KEYWORDS_BY_TYPE.get(answer_type, frozenset())

    if not unwanted:
        return blocks

    if any(question_explicitly_asks(question, keyword) for keyword in EXPLICIT_SECTION_KEYWORDS):
        return blocks

    cleaned_blocks: List[Dict[str, Any]] = []

    for block in blocks:
        title = coerce_string(block.get("title")).lower()

        if any(keyword in title for keyword in unwanted):
            continue

        if block.get("type") == "markdown":
            block = {
                **block,
                "content": strip_unwanted_markdown_sections(
                    coerce_string(block.get("content")),
                    answer_type,
                    question,
                ),
            }

            if not block["content"]:
                continue

        cleaned_blocks.append(block)

    return cleaned_blocks


def should_remove_image_block(block: Dict[str, Any], analysis: Dict[str, Any], answer_type: str) -> bool:
    """
    Avoids adding external image blocks where the visual is actually a table or optional.
    Example: TCP vs UDP needs a comparison table, not an image search result.
    """
    if block.get("type") != "image":
        return False

    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual_type = coerce_string((visual_support or {}).get("visual_type")).lower()
    visual_required = bool((visual_support or {}).get("visual_required"))

    if answer_type == "comparison" and ("table" in visual_type or not visual_required):
        return True

    return False


def remove_duplicate_conclusions(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keeps only one conclusion-like block to avoid repeated summary/future-scope endings."""
    cleaned: List[Dict[str, Any]] = []
    conclusion_seen = False

    for block in blocks:
        title = coerce_string(block.get("title")).lower()
        is_conclusion = "conclusion" in title or title in {"summary", "final answer"}

        if is_conclusion:
            if conclusion_seen:
                continue
            conclusion_seen = True

        cleaned.append(block)

    return cleaned


def transpose_two_row_comparison_table(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts weak table shape:
      columns = [Protocol, Reliability, Speed]
      rows    = [[TCP, ...], [UDP, ...]]
    into stronger exam shape:
      columns = [Parameter, TCP, UDP]
      rows    = [[Reliability, ..., ...], [Speed, ..., ...]]
    """
    columns = block.get("columns", [])
    rows = block.get("rows", [])

    if not isinstance(columns, list) or not isinstance(rows, list):
        return block

    if len(rows) != 2 or len(columns) < 3:
        return block

    first_row, second_row = rows[0], rows[1]

    if not isinstance(first_row, list) or not isinstance(second_row, list):
        return block

    if len(first_row) != len(columns) or len(second_row) != len(columns):
        return block

    concept_a = coerce_string(first_row[0])
    concept_b = coerce_string(second_row[0])

    if not concept_a or not concept_b:
        return block

    new_rows = []
    for index in range(1, len(columns)):
        parameter = coerce_string(columns[index])
        value_a = coerce_string(first_row[index])
        value_b = coerce_string(second_row[index])

        if parameter and (value_a or value_b):
            new_rows.append([parameter, value_a, value_b])

    if len(new_rows) < 3:
        return block

    return {
        **block,
        "columns": ["Parameter", concept_a, concept_b],
        "rows": new_rows,
    }


def normalize_comparison_tables(
    blocks: List[Dict[str, Any]],
    marks: int,
) -> List[Dict[str, Any]]:
    """Improves table shape and marks weak tables for easier frontend/debug handling."""
    required_rows = min_comparison_rows(marks)
    normalized: List[Dict[str, Any]] = []

    for block in blocks:
        if block.get("type") != "table":
            normalized.append(block)
            continue

        block = transpose_two_row_comparison_table(block)
        rows = block.get("rows", [])
        columns = block.get("columns", [])

        if isinstance(rows, list) and len(rows) < required_rows:
            block = {
                **block,
                "quality_warning": (
                    f"Comparison table has {len(rows)} rows. "
                    f"For {marks} marks, at least {required_rows} rows are recommended."
                ),
            }

        if isinstance(columns, list) and len(columns) == 3:
            first = coerce_string(columns[0]).lower()
            if first not in {"parameter", "basis", "feature", "point"}:
                block = {**block, "columns": ["Parameter", columns[1], columns[2]]}

        normalized.append(block)

    return normalized


def limit_comparison_intro(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prevents comparison answers from starting with a very long introduction."""
    for block in blocks:
        if block.get("type") != "markdown":
            continue

        title = coerce_string(block.get("title")).lower()
        if "introduction" not in title and "intro" not in title:
            continue

        content = coerce_string(block.get("content"))
        words = content.split()

        if len(words) > 140:
            block["content"] = " ".join(words[:140]).rstrip() + "..."

        break

    return blocks



def get_mandatory_visual_topic_rule(question: str) -> Optional[Dict[str, Any]]:
    lowered = f" {question.lower()} "

    for rule in MANDATORY_VISUAL_TOPIC_RULES:
        topic_any = rule.get("topic_any", ())
        question_any = rule.get("question_any", ())

        has_topic = any(f" {topic} " in lowered or topic in lowered for topic in topic_any)
        has_question_signal = any(f" {signal} " in lowered or signal in lowered for signal in question_any)

        if has_topic and has_question_signal:
            return dict(rule)

    return None


def get_recommended_visual_topic_rule(question: str) -> Optional[Dict[str, Any]]:
    lowered = f" {question.lower()} "

    for rule in RECOMMENDED_VISUAL_TOPIC_RULES:
        topic_any = rule.get("topic_any", ())
        question_any = rule.get("question_any", ())

        has_topic = all((f" {topic} " in lowered or topic in lowered) for topic in topic_any)
        has_question_signal = any(f" {signal} " in lowered or signal in lowered for signal in question_any)

        if has_topic and has_question_signal:
            return dict(rule)

    return None


def block_plan_requires_type(analysis: Dict[str, Any], block_type: str) -> bool:
    block_plan = analysis.get("block_plan") if isinstance(analysis, dict) else []
    if not isinstance(block_plan, list):
        return False
    return any(isinstance(item, dict) and coerce_string(item.get("type")).lower() == block_type for item in block_plan)


def preferred_visual_block(analysis: Dict[str, Any]) -> str:
    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual_support = visual_support if isinstance(visual_support, dict) else {}
    preferred = coerce_string(visual_support.get("preferred_visual_block")).lower()
    if preferred in {"image", "mermaid"}:
        return preferred
    if block_plan_requires_type(analysis, "mermaid"):
        return "mermaid"
    return "image"


def analysis_requires_image(analysis: Dict[str, Any], question: str) -> bool:
    # If the analyzer requested Mermaid as the preferred required visual, do not
    # force a separate image block. Mermaid will be enforced by ensure_required_mermaid_block().
    if preferred_visual_block(analysis) == "mermaid":
        return False

    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    if isinstance(visual_support, dict) and visual_support.get("visual_required") is True:
        return True

    if block_plan_requires_type(analysis, "image"):
        return True

    return get_mandatory_visual_topic_rule(question) is not None


def build_required_image_block_from_analysis(analysis: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Builds a safe image block when the LLM forgets a required visual."""
    topic_rule = get_mandatory_visual_topic_rule(question) or {}
    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual_support = visual_support if isinstance(visual_support, dict) else {}

    return {
        "type": "image",
        "title": (
            topic_rule.get("title")
            or coerce_string(visual_support.get("title"))
            or coerce_string(visual_support.get("visual_type"))
            or "Required Educational Diagram"
        ),
        "search_query": (
            topic_rule.get("image_search_query")
            or coerce_string(visual_support.get("image_search_query"))
            or f"{question} detailed labelled educational diagram"
        ),
        "recommended_websites": (
            topic_rule.get("recommended_websites")
            or visual_support.get("recommended_websites")
            or DEFAULT_RECOMMENDED_WEBSITES
        )[:2],
        "visual_type": topic_rule.get("visual_type") or visual_support.get("visual_type", "labelled educational diagram"),
        "diagram_labels": topic_rule.get("diagram_labels") or visual_support.get("diagram_labels", []),
    }


def analysis_recommends_visual(analysis: Dict[str, Any], question: str) -> bool:
    """True when a non-mandatory visual should be included for clarity."""
    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual_support = visual_support if isinstance(visual_support, dict) else {}

    if visual_support.get("visual_required") is True:
        return False

    if coerce_string(visual_support.get("visual_priority")).lower() == "recommended":
        return True

    return get_recommended_visual_topic_rule(question) is not None


def build_recommended_image_block_from_analysis(analysis: Dict[str, Any], question: str) -> Dict[str, Any]:
    rule = get_recommended_visual_topic_rule(question) or {}
    visual_support = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual_support = visual_support if isinstance(visual_support, dict) else {}

    return {
        "type": "image",
        "title": (
            rule.get("title")
            or coerce_string(visual_support.get("title"))
            or coerce_string(visual_support.get("visual_type"))
            or "Recommended Conceptual Visual"
        ),
        "search_query": (
            rule.get("image_search_query")
            or coerce_string(visual_support.get("image_search_query"))
            or f"{question} conceptual educational visual"
        ),
        "recommended_websites": (
            rule.get("recommended_websites")
            or visual_support.get("recommended_websites")
            or DEFAULT_RECOMMENDED_WEBSITES
        )[:2],
        "visual_type": rule.get("visual_type") or visual_support.get("visual_type", "conceptual educational visual"),
        "diagram_labels": rule.get("diagram_labels") or visual_support.get("diagram_labels", []),
    }


def ensure_recommended_visual_block(
    blocks: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    question: str,
) -> List[Dict[str, Any]]:
    """Adds a recommended image/visual when it improves clarity, without replacing tables."""
    if not analysis_recommends_visual(analysis, question):
        return blocks

    if any(block.get("type") in {"image", "mermaid"} for block in blocks):
        return blocks

    image_block = build_recommended_image_block_from_analysis(analysis, question)

    # For comparison answers, insert after intro and before the main table.
    for index, block in enumerate(blocks):
        if block.get("type") == "table":
            return blocks[:index] + [image_block] + blocks[index:]

    for index, block in enumerate(blocks):
        if block.get("type") == "markdown":
            title = coerce_string(block.get("title")).lower()
            if "intro" in title or "definition" in title:
                return blocks[: index + 1] + [image_block] + blocks[index + 1:]

    return [image_block] + blocks

def build_algorithm_mermaid_block(question: str) -> Dict[str, Any]:
    lowered = question.lower()

    if "binary search" in lowered:
        content = (
            "flowchart TD\n"
            "A([Start]) --> B[Input sorted array, target]\n"
            "B --> C[Set low = 0, high = n - 1]\n"
            "C --> D{low <= high?}\n"
            "D -- No --> E[Return -1 / Not Found]\n"
            "D -- Yes --> F[Compute mid = low + (high-low)//2]\n"
            "F --> G{array[mid] == target?}\n"
            "G -- Yes --> H[Return mid / Found]\n"
            "G -- No --> I{array[mid] < target?}\n"
            "I -- Yes --> J[Set low = mid + 1]\n"
            "I -- No --> K[Set high = mid - 1]\n"
            "J --> D\n"
            "K --> D\n"
            "H --> L([End])\n"
            "E --> L"
        )
        return {
            "type": "mermaid",
            "title": "Binary Search Flowchart",
            "diagram_type": "flowchart",
            "content": content,
        }

    return {
        "type": "mermaid",
        "title": "Algorithm Flowchart",
        "diagram_type": "flowchart",
        "content": (
            "flowchart TD\n"
            "A([Start]) --> B[Input data]\n"
            "B --> C[Initialize required variables]\n"
            "C --> D{Condition satisfied?}\n"
            "D -- Yes --> E[Process current step]\n"
            "E --> F[Update variables / move to next step]\n"
            "F --> D\n"
            "D -- No --> G[Return / Display result]\n"
            "G --> H([End])"
        ),
    }


def build_algorithm_code_block(question: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    lowered = question.lower()

    if "binary search" in lowered:
        return {
            "type": "code",
            "title": "Binary Search Pseudocode",
            "language": "pseudocode",
            "content": (
                "BinarySearch(array, target):\n"
                "    low = 0\n"
                "    high = length(array) - 1\n\n"
                "    while low <= high:\n"
                "        mid = low + (high - low) // 2\n\n"
                "        if array[mid] == target:\n"
                "            return mid\n"
                "        else if array[mid] < target:\n"
                "            low = mid + 1\n"
                "        else:\n"
                "            high = mid - 1\n\n"
                "    return -1"
            ),
            "explanation": [
                "The algorithm works only on a sorted array.",
                "At every iteration, it compares the target with the middle element.",
                "If the target is smaller, the right half is discarded; if larger, the left half is discarded.",
                "The search space becomes half after every comparison, giving logarithmic time complexity.",
            ],
            "output": "Returns the index of the target element if found; otherwise returns -1.",
        }

    return {
        "type": "code",
        "title": "Algorithm Pseudocode",
        "language": "pseudocode",
        "content": (
            "Algorithm(input):\n"
            "    initialize required variables\n"
            "    while termination condition is not reached:\n"
            "        process current step\n"
            "        update variables or state\n"
            "    return result"
        ),
        "explanation": [
            "This pseudocode represents the core control flow of the algorithm.",
            "Replace the processing and update steps according to the specific algorithm logic.",
        ],
        "output": "Returns the required result according to the algorithm.",
    }


def ensure_required_mermaid_block(
    blocks: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    question: str,
) -> List[Dict[str, Any]]:
    answer_type = get_analysis_answer_type(analysis, question)
    requires_mermaid = (
        block_plan_requires_type(analysis, "mermaid")
        or preferred_visual_block(analysis) == "mermaid"
        or answer_type == "algorithm"
    )
    if not requires_mermaid:
        return blocks

    if any(block.get("type") == "mermaid" for block in blocks):
        return blocks

    mermaid_block = build_algorithm_mermaid_block(question)

    for index, block in enumerate(blocks):
        if block.get("type") == "steps":
            return blocks[:index] + [mermaid_block] + blocks[index:]

    for index, block in enumerate(blocks):
        if block.get("type") == "markdown":
            title = coerce_string(block.get("title")).lower()
            if "intro" in title or "definition" in title:
                return blocks[: index + 1] + [mermaid_block] + blocks[index + 1:]

    return [mermaid_block] + blocks


def ensure_required_code_block(
    blocks: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    question: str,
) -> List[Dict[str, Any]]:
    answer_type = get_analysis_answer_type(analysis, question)
    requires_code = block_plan_requires_type(analysis, "code") or answer_type in {"algorithm", "code"}
    if not requires_code:
        return blocks

    if any(block.get("type") == "code" for block in blocks):
        return blocks

    code_block = build_algorithm_code_block(question, analysis)

    for index, block in enumerate(blocks):
        if block.get("type") == "steps":
            return blocks[: index + 1] + [code_block] + blocks[index + 1:]

    for index, block in enumerate(blocks):
        if block.get("type") == "mermaid":
            return blocks[: index + 1] + [code_block] + blocks[index + 1:]

    return blocks + [code_block]


def ensure_required_image_block(
    blocks: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    question: str,
) -> List[Dict[str, Any]]:
    """Guarantees an image block when analyzer/heuristics say visual is mandatory."""
    if not analysis_requires_image(analysis, question):
        return blocks

    if any(block.get("type") == "image" for block in blocks):
        return blocks

    image_block = build_required_image_block_from_analysis(analysis, question)

    # Put image immediately after first introduction markdown; if no intro exists, put first.
    for index, block in enumerate(blocks):
        if block.get("type") == "markdown":
            title = coerce_string(block.get("title")).lower()
            if "intro" in title or "definition" in title:
                return blocks[: index + 1] + [image_block] + blocks[index + 1:]

    return [image_block] + blocks


def quality_postprocess_output(
    payload: Dict[str, Any],
    analysis: Dict[str, Any],
    question: str,
    marks: int,
) -> Dict[str, Any]:
    """
    Final quality layer after schema validation.
    It removes irrelevant content, fixes weak comparison table shapes, and prevents unnecessary visuals.
    """
    blocks = payload.get("answer")
    if not isinstance(blocks, list):
        return payload

    answer_type = get_analysis_answer_type(analysis, question)

    blocks = [
        block
        for block in blocks
        if not should_remove_image_block(block, analysis, answer_type)
    ]

    blocks = ensure_required_mermaid_block(blocks, analysis, question)
    blocks = ensure_required_code_block(blocks, analysis, question)
    blocks = ensure_required_image_block(blocks, analysis, question)
    blocks = ensure_recommended_visual_block(blocks, analysis, question)
    blocks = remove_unwanted_blocks(blocks, answer_type, question)
    blocks = remove_duplicate_conclusions(blocks)

    if answer_type == "comparison":
        blocks = normalize_comparison_tables(blocks, marks)
        blocks = limit_comparison_intro(blocks)

    payload["answer"] = blocks
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Mermaid Fallback Generator
# ─────────────────────────────────────────────────────────────────────────────

MERMAID_SYSTEM_PROMPT = """\
You are a Mermaid diagram expert.
Return ONLY valid JSON with exactly three keys:
1. title
2. diagram_type
3. content

content must be valid Mermaid syntax only.
Do not include markdown fences.
Do not include commentary.
"""

MERMAID_PROMPT_TEMPLATE = """\
Generate a clear, educationally accurate Mermaid diagram for this topic.

Topic / diagram title: {title}
Context / full question: {question}

Rules:
- Use flowchart TD for architecture/system/process diagrams.
- Use sequenceDiagram only for request-response between named actors.
- Keep node labels short and readable.
- Avoid overly complex nested subgraphs.
- The diagram must make sense as a standalone educational visual.

Return ONLY valid JSON:
{{
  "title": "short diagram title",
  "diagram_type": "flowchart",
  "content": "valid Mermaid syntax only"
}}
"""


def generate_mermaid_for_image(
    image_block: Dict[str, Any],
    question: str,
) -> Optional[Dict[str, Any]]:
    title = coerce_string(image_block.get("title")) or question

    try:
        raw = openrouter_call(
            messages=[
                {"role": "system", "content": MERMAID_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": MERMAID_PROMPT_TEMPLATE.format(
                        title=title,
                        question=question,
                    ),
                },
            ],
            max_tokens=1000,
            temperature=0.2,
        )

        data = clean_json(raw)

        candidate = {
            "type": "mermaid",
            "title": data.get("title", title),
            "diagram_type": data.get("diagram_type", "flowchart"),
            "content": data.get("content", data.get("code", "")),
        }

        return validate_mermaid_block(candidate)

    except Exception as exc:
        logger.warning("Mermaid fallback failed for %r: %s", title, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Image Enrichment
# ─────────────────────────────────────────────────────────────────────────────

def image_block_for_fetcher(block: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts the new UI schema into a backward-compatible shape for older
    Diagram_fetcher implementations that may expect recommended_website.
    """
    websites = block.get("recommended_websites", DEFAULT_RECOMMENDED_WEBSITES)

    if isinstance(websites, list):
        recommended_website = ", ".join(
            str(site)
            for site in websites
            if str(site).strip()
        )
    else:
        recommended_website = str(websites)

    return {
        **block,
        "recommended_website": recommended_website,
    }


def enrich_images(payload: Dict[str, Any], question: str = "") -> Dict[str, Any]:
    """
    For every image block:
    1. Try to fetch real image URL through SerpAPI.
    2. If URL is found, keep image block and add "url".
    3. If URL is not found, replace image block with Mermaid fallback.
    4. If Mermaid also fails, keep original image block.
    """
    try:
        blocks = payload.get("answer")

        if not isinstance(blocks, list):
            return payload

        updated_blocks: List[Dict[str, Any]] = []

        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "image":
                url = None

                try:
                    url = get_image_link_from_serpapi(
                        image_block_for_fetcher(block)
                    )
                except Exception as exc:
                    logger.warning(
                        "Image fetch failed for %r: %s",
                        block.get("title"),
                        exc,
                    )

                if url:
                    updated_blocks.append({**block, "url": url})
                else:
                    fallback = generate_mermaid_for_image(block, question)
                    updated_blocks.append(fallback if fallback else block)
            else:
                updated_blocks.append(block)

        payload["answer"] = updated_blocks

    except Exception as exc:
        logger.warning("Image enrichment failed: %s", exc)

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Fallback Answer
# ─────────────────────────────────────────────────────────────────────────────

def needs_fallback_image(question: str, analysis: Dict[str, Any]) -> bool:
    searchable_text = " ".join([
        question.lower(),
        coerce_string(analysis.get("summary")).lower(),
        json.dumps(analysis, ensure_ascii=False).lower(),
    ])

    return (
        get_mandatory_visual_topic_rule(question) is not None
        or get_recommended_visual_topic_rule(question) is not None
        or any(keyword in searchable_text for keyword in VISUAL_KEYWORDS)
    )


def extract_sections(source: Any) -> List[Tuple[str, str]]:
    if not isinstance(source, list):
        return []

    sections: List[Tuple[str, str]] = []

    for item in source:
        if isinstance(item, dict):
            heading = (
                item.get("heading")
                or item.get("title")
                or item.get("name")
                or "Explanation"
            )
            content = (
                item.get("content")
                or item.get("summary")
                or item.get("description")
                or ""
            )
            sections.append((coerce_string(heading), coerce_string(content)))

        elif isinstance(item, str):
            sections.append((coerce_string(item), ""))

    return sections


def fallback_answer(
    question: str,
    analysis: Dict[str, Any],
    marks: int,
) -> Dict[str, Any]:
    summary = coerce_string(analysis.get("summary"))

    sections = (
        extract_sections(analysis.get("required_content"))
        or extract_sections(analysis.get("sections"))
    )

    answer_flow = analysis.get("answer_flow", [])
    scoring_keywords = analysis.get("scoring_keywords", [])
    examiner_focus = analysis.get("examiner_focus", [])

    blocks: List[Dict[str, Any]] = []

    intro = (
        summary
        or f"{question} is a core engineering concept that must be explained through definition, principle, working, components, applications, and conclusion."
    )

    blocks.append({
        "type": "markdown",
        "title": "Introduction",
        "content": (
            "## Introduction\n\n"
            f"{intro}\n\n"
            "This answer is structured in a university-exam format so that the concept is introduced clearly, developed through technical explanation, and concluded with engineering significance."
        ),
    })

    if needs_fallback_image(question, analysis):
        blocks.append({
            "type": "image",
            "title": f"{question} Diagram",
            "search_query": f"{question} detailed labelled educational diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        })

    if sections:
        section_parts: List[str] = []

        for heading, content in sections:
            section_parts.append(f"## {heading}")
            section_parts.append(
                content
                or "This section should be explained with technical precision, including definition, internal working, sub-points, examples, and engineering relevance."
            )

        blocks.append({
            "type": "markdown",
            "title": "Detailed Explanation",
            "content": "\n\n".join(section_parts),
        })
    else:
        blocks.append({
            "type": "markdown",
            "title": "Detailed Explanation",
            "content": (
                "## Detailed Explanation\n\n"
                "The concept should be explained by covering its formal definition, underlying principle, internal working, important components, and practical importance. "
                "A full-mark answer must avoid vague statements and should connect every point to engineering use."
            ),
        })

    exam_parts: List[str] = []

    if isinstance(answer_flow, list) and answer_flow:
        exam_parts.append("## Suggested Answer Flow")
        exam_parts.extend(
            f"- {coerce_string(item).replace('_', ' ').title()}"
            for item in answer_flow
        )

    if isinstance(examiner_focus, list) and examiner_focus:
        exam_parts.append("## Examiner Focus")
        exam_parts.extend(
            f"- {coerce_string(item).replace('_', ' ')}"
            for item in examiner_focus
        )

    if isinstance(scoring_keywords, list) and scoring_keywords:
        exam_parts.append("## Key Technical Terms")
        exam_parts.append(
            ", ".join(
                coerce_string(item).replace("_", " ")
                for item in scoring_keywords
            )
        )

    if marks >= 6:
        exam_parts.append("## Technical Analysis")
        exam_parts.append(
            "For a strong answer, explain the mechanism at data-flow, control-flow, architectural, mathematical, or implementation level depending on the subject."
        )

    if marks >= 8:
        exam_parts.append("## Applications")
        exam_parts.append(
            "Include real systems, standards, protocols, tools, or products, and explain exactly how each one uses the concept."
        )

    exam_parts.append("## Conclusion")
    exam_parts.append(
        "The concept is important because it connects theoretical principles with practical engineering implementation. "
        "A complete answer should restate the definition, summarize the working mechanism, explain technical significance, mention limitations, and indicate future scope."
    )

    blocks.append({
        "type": "markdown",
        "title": "Exam-Focused Additions",
        "content": "\n\n".join(exam_parts),
    })

    return {
        "question": question,
        "answer": blocks,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Mandatory Image Policy - Removed
# ─────────────────────────────────────────────────────────────────────────────
# Removed to allow dynamic formats based on subject context.


def normalize_websites_for_image(websites: Any) -> List[str]:
    values = coerce_string_list(websites, DEFAULT_RECOMMENDED_WEBSITES)
    return values[:2] or DEFAULT_RECOMMENDED_WEBSITES


def image_identity(block: Dict[str, Any]) -> str:
    return (
        coerce_string(block.get("search_query"))
        or coerce_string(block.get("title"))
    ).lower()


def fallback_image_block(question: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    visual = analysis.get("visual_support") if isinstance(analysis, dict) else {}
    visual = visual if isinstance(visual, dict) else {}

    topic_rule = get_mandatory_visual_topic_rule(question) or get_recommended_visual_topic_rule(question) or {}

    return {
        "type": "image",
        "title": (
            topic_rule.get("title")
            or coerce_string(visual.get("title"))
            or coerce_string(visual.get("visual_type"))
            or "Educational Concept Diagram"
        ),
        "search_query": (
            topic_rule.get("image_search_query")
            or coerce_string(visual.get("image_search_query"))
            or f"{question} educational labelled diagram"
        ),
        "recommended_websites": normalize_websites_for_image(
            topic_rule.get("recommended_websites")
            or visual.get("recommended_websites")
        ),
        "visual_type": (
            topic_rule.get("visual_type")
            or coerce_string(visual.get("visual_type"))
            or "educational concept diagram"
        ),
        "diagram_labels": topic_rule.get("diagram_labels") or visual.get("diagram_labels", []),
    }


def apply_final_quality_layer(
    payload: Dict[str, Any],
    analysis: Dict[str, Any],
    question: str,
    marks: int,
) -> Dict[str, Any]:
    """
    Final answer post-processing without overriding existing functions.
    It preserves all previous quality logic.
    """
    return quality_postprocess_output(payload, analysis, question, marks)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_answer_via_openrouter(
    question: str,
    analysis: Optional[Dict[str, Any]],
    expected_marks: int = 8,
) -> Dict[str, Any]:
    """
    Generate a deeply detailed, exam-ready answer as ordered UI content blocks.

    Output schema:
    {
        "question": "...",
        "answer": [
            {
                "type": "markdown",
                "title": "...",
                "content": "..."
            },
            {
                "type": "image",
                "title": "...",
                "search_query": "...",
                "recommended_websites": ["...", "..."],
                "url": "..."
            },
            {
                "type": "table",
                "title": "...",
                "columns": ["...", "..."],
                "rows": [["...", "..."]]
            },
            {
                "type": "steps",
                "title": "...",
                "items": [
                    {"step": 1, "content": "..."}
                ]
            },
            {
                "type": "mermaid",
                "title": "...",
                "diagram_type": "flowchart",
                "content": "flowchart TD\\nA --> B"
            },
            {
                "type": "code",
                "title": "...",
                "language": "python",
                "content": "...",
                "explanation": ["..."],
                "output": "..."
            }
        ]
    }
    """
    analysis = normalize_analysis(analysis)
    question = coerce_string(question)

    if not question:
        return {
            "question": "",
            "answer": [
                {
                    "type": "markdown",
                    "title": "Error",
                    "content": "Question is required to generate an answer.",
                }
            ],
        }

    if not isinstance(expected_marks, int) or expected_marks <= 0:
        expected_marks = 8

    try:
        from app.core.config import settings
        system_prompt = select_system_prompt(analysis, question)
        models_to_try = list(settings.OPENROUTER_MODELS_POOL)
        import random
        random.shuffle(models_to_try)
        
        last_error = None
        for m in dict.fromkeys(m for m in models_to_try if m):
            try:
                raw = openrouter_call(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": build_prompt(question, analysis, expected_marks),
                        },
                    ],
                    model=m,
                    max_tokens=MAX_TOKENS,
                    temperature=0.22,
                )

                parsed = clean_json(raw)
                validated = validate_output(parsed, question)
                improved = apply_final_quality_layer(
                    payload=validated,
                    analysis=analysis,
                    question=question,
                    marks=expected_marks,
                )

                return enrich_images(improved, question)
            except Exception as loop_exc:
                last_error = loop_exc
                logger.warning("Generation with model %s failed (possibly JSON error): %s", m, loop_exc)

        # If all models fail, raise the last error so it falls into the outer exception handler
        raise last_error if last_error else RuntimeError("All models failed")

    except Exception as exc:
        logger.exception("OpenRouter answer generation failed: %s", exc)

        return {
            "question": question,
            "answer": [
                {
                    "type": "markdown",
                    "title": "⚠️ AI Limit Reached",
                    "content": "Our AI service has currently reached its token or usage limit, or the generation was unexpectedly interrupted. Please try again in a few moments, or break your question down into smaller parts.",
                }
            ],
            "is_error": True
        }


def generate_answer_via_gemini_strict(
    question: str,
    analysis: Optional[Dict[str, Any]],
    expected_marks: int = 8,
) -> Dict[str, Any]:
    """
    Generate the final answer using Google Gemini 2.0 Flash with Structured Outputs (Strict JSON).
    """
    try:
        from app.services.ai.gemini_client import chat_completion as gemini_call
        
        system_prompt = select_system_prompt(analysis, question)
        
        raw = gemini_call(
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": build_prompt(question, analysis, expected_marks),
                },
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.22,
            response_mime_type="application/json"
        )

        parsed = clean_json(raw)
        validated = validate_output(parsed, question)
        improved = apply_final_quality_layer(
            payload=validated,
            analysis=analysis,
            question=question,
            marks=expected_marks,
        )

        return enrich_images(improved, question)

    except Exception as exc:
        logger.error("Gemini strict answer generation failed: %s", exc, exc_info=True)
        return {
            "question": question,
            "answer": [
                {
                    "type": "markdown",
                    "title": "⚠️ AI Limit Reached",
                    "content": "Our AI service has currently reached its token or usage limit, or the generation was unexpectedly interrupted. Please try again in a few moments, or break your question down into smaller parts.",
                }
            ],
            "is_error": True
        }


def generate_answer_via_groq(
    question: str,
    analysis: Optional[Dict[str, Any]],
    expected_marks: int = 8,
) -> Dict[str, Any]:
    """
    Generate the final answer using Groq API (Llama 3.3 70B).
    """
    try:
        from app.services.ai.groq_client import chat_completion as groq_call
        
        system_prompt = select_system_prompt(analysis, question)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": build_prompt(question, analysis, expected_marks),
            },
        ]
        
        try:
            raw = groq_call(
                messages=messages,
                max_tokens=8000,
                temperature=0.22,
            )
        except Exception as groq_exc:
            logger.warning("Groq failed (%s), falling back to Gemini...", groq_exc)
            from app.services.ai.gemini_client import chat_completion as gemini_call
            raw = gemini_call(
                messages=messages,
                max_tokens=8000,
                temperature=0.22,
            )


        parsed = clean_json(raw)
        validated = validate_output(parsed, question)
        improved = apply_final_quality_layer(
            payload=validated,
            analysis=analysis,
            question=question,
            marks=expected_marks,
        )

        return enrich_images(improved, question)

    except Exception as exc:
        logger.error("Groq answer generation failed: %s", exc, exc_info=True)
        return {
            "question": question,
            "answer": [
                {
                    "type": "markdown",
                    "title": "⚠️ Groq AI Limit Reached",
                    "content": "Our AI service has reached its strict 1 question per minute limit on Groq. Please wait for exactly 60 seconds before generating the next question.",
                }
            ],
            "is_error": True
        }


# ─────────────────────────────────────────────────────────────────────────────
# Dev Smoke Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample_analysis = {
        "summary": "Explain the OSI model with all seven layers in detail.",
        "required_content": [
            {
                "heading": "Introduction",
                "content": "The OSI model is a seven-layer conceptual framework for standardizing network communication.",
            },
            {
                "heading": "Seven Layers",
                "content": "Physical, Data Link, Network, Transport, Session, Presentation, and Application layers must be explained with their functions, protocols, and examples.",
            },
            {
                "heading": "Working",
                "content": "Explain encapsulation from the Application layer down to the Physical layer and decapsulation at the receiver side.",
            },
        ],
        "answer_flow": [
            "introduction",
            "layer_explanation",
            "encapsulation",
            "diagram",
            "applications",
        ],
        "visuals": [
            "OSI Model layered diagram",
            "data encapsulation illustration",
        ],
        "scoring_keywords": [
            "physical_layer",
            "data_link_layer",
            "network_layer",
            "transport_layer",
            "session_layer",
            "presentation_layer",
            "application_layer",
            "encapsulation",
            "PDU",
            "MAC_address",
            "IP_address",
            "TCP_segment",
        ],
        "examiner_focus": [
            "layer_functions",
            "PDU_names",
            "protocol_examples",
            "encapsulation_process",
        ],
    }

    result = generate_answer_via_openrouter(
        question="Explain the OSI Model in detail with diagram and layer-wise functions.",
        analysis=sample_analysis,
        expected_marks=10,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
