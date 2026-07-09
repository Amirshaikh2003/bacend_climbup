"""
Dynamic Engineering Question Analyzer - Quality Improved
-------------------------------------------------------
Purpose:
- Analyze any BE/BTech engineering exam question.
- Return a compact, strict, high-quality JSON blueprint.
- Do NOT generate the final answer here.
- The answer generator should follow `block_plan` exactly.

Key improvements:
- Better answer_type inference with safer precedence.
- Comparison questions no longer mark tables as external visuals.
- Dynamic block_plan optimized for exam quality.
- Marks-aware depth, row counts, and section selection.
- Stronger validation and normalization of analyzer output.
- Safer fallback blueprint when the LLM fails.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.services.ai.groq_client import chat_completion

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_ANSWER_TYPES = frozenset({
    "text",
    "comparison",
    "process",
    "sequence",
    "hierarchy",
    "graph",
    "timeline",
    "formula",
    "calculation",
    "algorithm",
    "code",
    "image",
})

ALLOWED_BLOCK_TYPES = frozenset({"markdown", "image", "table", "steps", "mermaid", "code"})
ALLOWED_VISUAL_PRIORITIES = frozenset({"required", "recommended", "optional"})

DEFAULT_RECOMMENDED_WEBSITES = ["GeeksforGeeks", "Wikipedia"]

# Explicit visual words: if these appear, visual is usually required.
EXPLICIT_VISUAL_KEYWORDS = frozenset({
    "diagram", "labelled diagram", "labeled diagram", "neat sketch", "draw",
    "draw and explain", "architecture", "block diagram", "circuit diagram",
    "flowchart", "memory map", "timing diagram", "waveform", "graph", "plot",
    "curve", "topology", "er diagram", "uml", "class diagram", "state diagram",
    "sequence diagram", "data flow diagram", "dfd",
})

# Structural terms can help identify type, but should not always trigger external images.
STRUCTURAL_VISUAL_HINTS = frozenset({
    "model", "layers", "hierarchy", "classification", "structure", "working",
    "process", "lifecycle", "mechanism", "data flow", "pipeline", "organization",
})


# Concepts that usually need a diagram/flowchart/lifecycle visual for full-mark answers
# even when the question does not explicitly say "draw diagram".
# Example: "What is Machine Learning? What are steps in Machine Learning? Explain."
# This should force an image block for ML workflow/lifecycle.
MANDATORY_VISUAL_TOPIC_RULES = (
    {
        "topic_any": ("machine learning", "ml"),
        "question_any": ("steps", "process", "workflow", "lifecycle", "life cycle", "pipeline", "working"),
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
        "why_visual_needed": "The question asks for the steps in Machine Learning, so a workflow/lifecycle diagram is important for full-mark presentation.",
    },
    {
        "topic_any": ("software development life cycle", "sdlc"),
        "question_any": ("steps", "phases", "process", "lifecycle", "life cycle"),
        "visual_type": "SDLC phases diagram",
        "diagram_labels": ["Planning", "Analysis", "Design", "Implementation", "Testing", "Deployment", "Maintenance"],
        "image_search_query": "SDLC phases lifecycle diagram",
        "why_visual_needed": "The question asks for SDLC phases/steps, so a lifecycle diagram is required for clear exam presentation.",
    },
    {
        "topic_any": ("compiler",),
        "question_any": ("phases", "passes", "working", "process", "structure"),
        "visual_type": "Compiler phases diagram",
        "diagram_labels": ["Lexical analysis", "Syntax analysis", "Semantic analysis", "Intermediate code", "Optimization", "Code generation"],
        "image_search_query": "compiler phases labelled diagram",
        "why_visual_needed": "Compiler phase questions are best answered with a labelled phase diagram.",
    },
    {
        "topic_any": ("instruction cycle", "fetch decode execute"),
        "question_any": ("steps", "working", "cycle", "process"),
        "visual_type": "Instruction cycle flow diagram",
        "diagram_labels": ["Fetch", "Decode", "Execute", "Memory access", "Write back", "Next instruction"],
        "image_search_query": "instruction cycle fetch decode execute flow diagram",
        "why_visual_needed": "Instruction-cycle questions require a flow diagram to show the ordered CPU stages.",
    },
    {
        "topic_any": ("osi", "tcp/ip", "tcp ip"),
        "question_any": ("model", "layers", "architecture", "explain"),
        "visual_type": "Layered network model diagram",
        "diagram_labels": ["Application", "Transport", "Network", "Data Link", "Physical"],
        "image_search_query": "OSI TCP IP layered model diagram",
        "why_visual_needed": "Layered network model questions need a layered diagram for full-mark clarity.",
    },
)

# Topics where an external/conceptual visual is not mandatory, but strongly improves
# clarity and answer presentation. This is especially useful for ML/Data Science
# comparisons, where a small diagram can show output type or decision behavior.
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
        "why_visual_needed": "A conceptual visual helps distinguish categorical output in classification from continuous numeric output in regression.",
    },
    {
        "topic_any": ("supervised learning", "unsupervised learning"),
        "question_any": ("compare", "comparison", "differentiate", "distinguish", "difference", " vs ", "versus"),
        "title": "Supervised vs Unsupervised Learning Visual Comparison",
        "visual_type": "conceptual visual comparison",
        "diagram_labels": ["Machine Learning", "Supervised Learning", "Unsupervised Learning", "Labeled Data", "Unlabeled Data", "Example"],
        "image_search_query": "supervised vs unsupervised learning visual comparison",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
        "why_visual_needed": "A visual comparison helps students quickly understand the difference between labeled-data and unlabeled-data learning.",
    },
    {
        "topic_any": ("classification", "clustering"),
        "question_any": ("compare", "comparison", "differentiate", "distinguish", "difference", " vs ", "versus"),
        "title": "Classification vs Clustering Visual Comparison",
        "visual_type": "conceptual visual comparison",
        "diagram_labels": ["Machine Learning", "Classification", "Clustering", "Known Classes", "Discovered Groups", "Example"],
        "image_search_query": "classification vs clustering visual comparison machine learning",
        "recommended_websites": ["GeeksforGeeks", "IBM"],
        "why_visual_needed": "A visual is helpful because classification uses predefined labels while clustering discovers natural groups.",
    },
)


COMPARISON_SIGNALS = frozenset({
    "compare", "comparison", "differentiate", "distinguish", "difference between",
    "differences between", "versus", " vs ", " tcp vs ", " udp vs ",
    "merits and demerits", "advantages and disadvantages", "advantages vs disadvantages",
})

PROCESS_SIGNALS = frozenset({
    "working", "operation", "mechanism", "procedure", "steps", "process",
    "lifecycle", "life cycle", "flow", "how does", "explain working", "functioning",
})

CALCULATION_SIGNALS = frozenset({
    "calculate", "compute", "determine", "evaluate", "solve numerically",
    "numerical", "find the value", "find total", "find average", "given that",
})

FORMULA_SIGNALS = frozenset({
    "derive", "derivation", "expression", "formula", "equation", "relation",
    "prove that", "show that",
})

CODE_SIGNALS = frozenset({
    "write a program", "program to", "code", "implementation", "implement",
    "sql", "query", "script", "html", "css", "javascript", "python", "java program",
    "c program", "c++ program", "cpp program",
})

ALGORITHM_SIGNALS = frozenset({
    "algorithm", "pseudocode", "pseudo code", "flowchart", "complexity",
    "time complexity", "space complexity", "big o", "big-o",
})

HIERARCHY_SIGNALS = frozenset({
    "classify", "classification", "types", "layers", "levels", "architecture",
    "model", "taxonomy", "hierarchy", "components", "modules",
})

GRAPH_SIGNALS = frozenset({
    "graph", "plot", "curve", "waveform", "characteristics", "x-axis", "y-axis",
    "input characteristics", "output characteristics", "frequency response",
})

TIMELINE_SIGNALS = frozenset({
    "history", "evolution", "timeline", "phases", "generations", "development of",
})

IMAGE_SIGNALS = frozenset({
    "draw", "neat sketch", "labelled diagram", "labeled diagram", "circuit diagram",
    "block diagram", "architecture diagram", "timing diagram", "waveform",
})

# Useful when the analyzer LLM misses obvious technical keywords.
GENERIC_SCORING_KEYWORDS = {
    "comparison": ["parameter-wise comparison", "technical difference", "applications", "practical implication"],
    "process": ["sequence", "working", "input", "output", "data flow"],
    "sequence": ["ordered steps", "stages", "control flow", "final result"],
    "hierarchy": ["layers/types", "function of each", "relationship", "examples"],
    "graph": ["axis labels", "curve shape", "regions", "interpretation"],
    "timeline": ["phase", "chronology", "development", "significance"],
    "formula": ["formula", "symbols", "units", "assumptions", "final expression"],
    "calculation": ["given data", "formula", "substitution", "units", "final answer"],
    "algorithm": ["input", "logic", "pseudocode", "complexity", "edge cases"],
    "code": ["complete code", "input", "logic", "output", "comments"],
    "image": ["labels", "components", "diagram explanation"],
    "text": ["definition", "principle", "working", "applications", "conclusion"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""
You are a strict engineering exam question analyzer.
You do NOT write the final answer.
You produce a JSON blueprint that another AI will use to generate a full-mark BE/BTech engineering answer.

Allowed answer_type values:
{sorted(ALLOWED_ANSWER_TYPES)}

Allowed visual_priority values:
{sorted(ALLOWED_VISUAL_PRIORITIES)}

Return ONLY valid JSON.
Do not include markdown fences.
Do not include commentary outside JSON.
Do not solve numericals.
Do not write full code.
Do not write the actual topic explanation.

Your JSON must contain these keys:
- answer_type
- question_intent
- difficulty
- depth_level
- full_marks_answer_structure
- must_include
- scoring_keywords
- examiner_focus
- answer_strategy
- visual_support
- block_plan

The block_plan is critical.
It must tell the answer generator exactly which UI blocks to create and in what order.
Allowed block types in block_plan:
- markdown
- image
- table
- steps
- mermaid
- code

For each block_plan item include:
- type
- title
- purpose
- required_points

For table blocks also include suggested_columns and minimum_rows.
For image blocks include visual_type, search_query, diagram_labels, recommended_websites.
For steps blocks include step_focus and minimum_steps.
For code blocks include language_hint and code_requirements.

Very important rules:
1. For comparison questions, the main visual is a TABLE BLOCK, not an external image. Set visual_required=false unless the question explicitly asks for a diagram/graph.
2. For comparison questions, use columns: Parameter, First Concept, Second Concept. Do not make rows as only concept names.
3. Do not include History, Future Scope, or long background unless the question explicitly asks.
4. Numericals must use steps format: given data, formula, substitution, calculation, units, final answer.
5. Code questions must include complete code, explanation, sample output, and complexity if relevant.
"""

USER_PROMPT_TEMPLATE = """
Analyze this engineering exam question and return a dynamic answer blueprint.

Question:
{question}

Context:
Branch: {branch}
Subject: {subject}
Unit/Module: {unit}
Expected Marks: {marks}
Syllabus/Topic Context: {syllabus}

Rules:
1. Select exactly one answer_type.
2. The blueprint must help generate a full-mark answer.
3. Do not answer the question.
4. Decide exact sections and UI blocks needed.
5. Use image/table/steps/code only when useful.
6. If the question explicitly asks for diagram, graph, architecture, model diagram, flowchart, waveform, circuit, topology, or labelled figure, visual_support must be required.
7. For comparison questions, visual_support should usually be optional because the required comparison table is a table block, not an image.
8. If marks are high, include deeper sections such as working, applications, limitations, and conclusion.
9. Keep the JSON compact but complete.

Return JSON only using this shape:
{{
  "answer_type": "text | comparison | process | sequence | hierarchy | graph | timeline | formula | calculation | algorithm | code | image",
  "question_intent": "string",
  "difficulty": "easy | medium | hard",
  "depth_level": "short | medium | detailed | exhaustive",
  "full_marks_answer_structure": ["section names"],
  "must_include": ["important scoring content"],
  "scoring_keywords": ["technical keywords"],
  "examiner_focus": ["what examiner checks"],
  "answer_strategy": {{
    "opening_style": "definition_first | direct_solution | comparison_first | diagram_first",
    "explanation_style": "theory | layer_wise | stepwise | tabular | mathematical | code_first",
    "exam_orientation": "string",
    "avoid": ["mistakes to avoid"]
  }},
  "visual_support": {{
    "visual_required": true,
    "visual_priority": "required | recommended | optional",
    "visual_type": "string",
    "why_visual_needed": "string",
    "diagram_labels": ["labels"],
    "image_search_query": "string",
    "recommended_websites": ["website", "website"]
  }},
  "block_plan": [
    {{
      "type": "markdown",
      "title": "string",
      "purpose": "string",
      "required_points": ["points"]
    }}
  ]
}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Generic Helpers
# ─────────────────────────────────────────────────────────────────────────────

def coerce_string(value: Any) -> str:
    return str(value or "").strip()


def coerce_int(value: Any, default: int = 8) -> int:
    try:
        number = int(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default


def coerce_string_list(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    if fallback is None:
        fallback = []

    if isinstance(value, list):
        return [coerce_string(item) for item in value if coerce_string(item)]

    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value.strip()] if value.strip() else fallback

    return fallback


def unique_list(items: List[str], max_items: Optional[int] = None) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        clean = coerce_string(item)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result[:max_items] if max_items else result


def contains_any(text: str, signals: frozenset[str]) -> bool:
    lowered = f" {text.lower()} "
    return any(signal in lowered for signal in signals)


def has_explicit_visual_request(question: str) -> bool:
    return contains_any(question, EXPLICIT_VISUAL_KEYWORDS | IMAGE_SIGNALS)



def get_mandatory_visual_topic_rule(question: str) -> Optional[Dict[str, Any]]:
    """
    Returns a topic-specific visual rule when a diagram/flowchart should be
    mandatory even if the question does not literally contain "draw diagram".
    """
    lowered = f" {question.lower()} "

    for rule in MANDATORY_VISUAL_TOPIC_RULES:
        topic_any = rule.get("topic_any", ())
        question_any = rule.get("question_any", ())

        has_topic = any(f" {topic} " in lowered or topic in lowered for topic in topic_any)
        has_question_signal = any(f" {signal} " in lowered or signal in lowered for signal in question_any)

        if has_topic and has_question_signal:
            return dict(rule)

    return None


def requires_mandatory_visual(question: str, answer_type: str) -> bool:
    """True when visual must be generated for full-mark presentation."""
    if has_explicit_visual_request(question):
        return True

    if get_mandatory_visual_topic_rule(question):
        return True

    # Graph and image answers are visual-first by nature.
    if answer_type in {"image", "graph"}:
        return True

    return False


def clean_json_response(raw: str) -> Dict[str, Any]:
    if not raw or not raw.strip():
        raise ValueError("AI returned an empty response")

    text = raw.strip()

    # Remove hidden reasoning blocks if a provider leaks them.
    if "<think>" in text:
        end = text.find("</think>")
        text = text[end + 8:].strip() if end != -1 else text

    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    normalized = re.sub(r"\bNone\b", "null", text)
    normalized = re.sub(r"\bTrue\b", "true", normalized)
    normalized = re.sub(r"\bFalse\b", "false", normalized)
    normalized = re.sub(r",\s*([}\]])", r"\1", normalized)

    try:
        parsed = json.loads(normalized)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    start = normalized.find("{")
    if start == -1:
        raise ValueError("No JSON object found in AI response")

    parsed, _ = decoder.raw_decode(normalized[start:])
    if not isinstance(parsed, dict):
        raise ValueError("Parsed JSON must be an object")
    return parsed


def remove_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            cleaned_item = remove_empty_values(item)
            if key == "visual_required" and isinstance(cleaned_item, bool):
                cleaned[key] = cleaned_item
            elif cleaned_item not in ("", None, [], {}):
                cleaned[key] = cleaned_item
        return cleaned

    if isinstance(value, list):
        return [
            item
            for item in (remove_empty_values(x) for x in value)
            if item not in ("", None, [], {})
        ]

    return value

# ─────────────────────────────────────────────────────────────────────────────
# Type / Depth / Strategy Inference
# ─────────────────────────────────────────────────────────────────────────────

def infer_answer_type(question: str) -> str:
    """
    Deterministic fallback answer type.
    Precedence matters: e.g. "time complexity" should be algorithm, not calculation.
    "derive expression" should be formula, not text.
    "write program" should be code.
    "differentiate" should be comparison even if it includes applications.
    """
    q = question.lower()

    if contains_any(q, COMPARISON_SIGNALS):
        return "comparison"
    if contains_any(q, CODE_SIGNALS):
        return "code"
    if contains_any(q, ALGORITHM_SIGNALS):
        return "algorithm"
    if contains_any(q, FORMULA_SIGNALS):
        return "formula"
    if contains_any(q, CALCULATION_SIGNALS):
        return "calculation"
    if contains_any(q, GRAPH_SIGNALS):
        return "graph"
    if contains_any(q, TIMELINE_SIGNALS):
        return "timeline"
    if contains_any(q, PROCESS_SIGNALS):
        return "process"
    if contains_any(q, HIERARCHY_SIGNALS):
        return "hierarchy"
    if contains_any(q, IMAGE_SIGNALS):
        return "image"
    return "text"


def depth_from_marks(marks: int) -> str:
    if marks >= 12:
        return "exhaustive"
    if marks >= 8:
        return "detailed"
    if marks >= 4:
        return "medium"
    return "short"


def difficulty_from_marks(marks: int) -> str:
    if marks >= 10:
        return "hard"
    if marks >= 5:
        return "medium"
    return "easy"


def min_table_rows_for_marks(marks: int) -> int:
    if marks >= 12:
        return 10
    if marks >= 8:
        return 8
    if marks >= 4:
        return 6
    return 4


def min_steps_for_marks(marks: int) -> int:
    if marks >= 12:
        return 8
    if marks >= 8:
        return 6
    if marks >= 4:
        return 4
    return 3


def infer_answer_strategy(answer_type: str, question: str) -> Dict[str, Any]:
    if answer_type == "comparison":
        return {
            "opening_style": "comparison_first",
            "explanation_style": "tabular",
            "exam_orientation": "table-dominant parameter-wise comparison answer",
            "avoid": [
                "long history unless asked",
                "future scope unless asked",
                "repeating table rows in paragraphs",
                "using concept names as rows instead of parameters",
            ],
        }

    if answer_type == "calculation":
        return {
            "opening_style": "direct_solution",
            "explanation_style": "mathematical",
            "exam_orientation": "step-by-step numerical solution with units",
            "avoid": ["skipping formula", "missing units", "jumping directly to final answer"],
        }

    if answer_type == "code":
        return {
            "opening_style": "code_first",
            "explanation_style": "code_first",
            "exam_orientation": "complete runnable exam-suitable implementation",
            "avoid": ["incomplete code", "missing output", "missing logic explanation"],
        }

    if answer_type in {"process", "sequence", "algorithm"}:
        return {
            "opening_style": "definition_first",
            "explanation_style": "stepwise",
            "exam_orientation": "ordered working with clear input, processing, and output",
            "avoid": ["unordered explanation", "missing flow", "vague steps"],
        }

    if answer_type in {"hierarchy", "image", "graph"}:
        return {
            "opening_style": "diagram_first" if has_explicit_visual_request(question) else "definition_first",
            "explanation_style": "layer_wise" if answer_type == "hierarchy" else "theory",
            "exam_orientation": "diagram-supported explanation with labels and interpretation",
            "avoid": ["unlabelled diagram", "missing function of components", "generic explanation"],
        }

    return {
        "opening_style": "definition_first",
        "explanation_style": "theory",
        "exam_orientation": "full-mark university answer",
        "avoid": ["vague statements", "unnecessary repetition", "missing examples"],
    }

# ─────────────────────────────────────────────────────────────────────────────
# Visual Support
# ─────────────────────────────────────────────────────────────────────────────

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


def build_recommended_visual_support(rule: Dict[str, Any], question: str) -> Dict[str, Any]:
    return {
        "visual_required": False,
        "visual_priority": "recommended",
        "visual_type": rule.get("visual_type", "conceptual educational visual"),
        "why_visual_needed": rule.get("why_visual_needed", "A visual can improve conceptual clarity and exam presentation."),
        "diagram_labels": list(rule.get("diagram_labels", [])) or ["main concept", "comparison", "example"],
        "image_search_query": rule.get("image_search_query", f"{question} conceptual visual comparison"),
        "recommended_websites": list(rule.get("recommended_websites", DEFAULT_RECOMMENDED_WEBSITES))[:2] or DEFAULT_RECOMMENDED_WEBSITES,
    }


def build_default_visual_support(question: str, answer_type: str) -> Dict[str, Any]:
    explicit_visual = has_explicit_visual_request(question)
    mandatory_topic_rule = get_mandatory_visual_topic_rule(question)
    recommended_topic_rule = get_recommended_visual_topic_rule(question)

    if recommended_topic_rule and not explicit_visual and not mandatory_topic_rule:
        return build_recommended_visual_support(recommended_topic_rule, question)

    # Important: comparison table is a table block, not an external visual,
    # unless the question explicitly asks for a diagram/flowchart/graph.
    if answer_type == "comparison" and not explicit_visual and not mandatory_topic_rule:
        return {
            "visual_required": False,
            "visual_priority": "optional",
            "visual_type": "comparison table block",
            "why_visual_needed": "A table is required as an answer block, but no external diagram/image is required for this comparison question.",
            "diagram_labels": ["Parameter", "First Concept", "Second Concept"],
            "image_search_query": f"{question} comparison table",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        }

    if mandatory_topic_rule:
        return {
            "visual_required": True,
            "visual_priority": "required",
            "visual_type": mandatory_topic_rule.get("visual_type", "required educational workflow diagram"),
            "why_visual_needed": mandatory_topic_rule.get("why_visual_needed", "This question needs a visual workflow/diagram for full-mark presentation."),
            "diagram_labels": list(mandatory_topic_rule.get("diagram_labels", [])) or ["input", "process", "output"],
            "image_search_query": mandatory_topic_rule.get("image_search_query", f"{question} labelled educational diagram"),
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        }

    visual_required = requires_mandatory_visual(question, answer_type)

    if visual_required:
        return {
            "visual_required": True,
            "visual_priority": "required",
            "visual_type": "labelled educational diagram / graph / architecture / workflow",
            "why_visual_needed": "The question requires a diagram, graph, architecture, waveform, flowchart, or visual representation for full-mark presentation.",
            "diagram_labels": ["main components", "important labels", "direction of flow", "input/output where applicable"],
            "image_search_query": f"{question} detailed labelled educational diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        }

    # Algorithm questions should normally include a flowchart-style Mermaid diagram.
    # This is treated as mandatory for full-mark algorithm answers, even when the
    # question does not explicitly say "draw flowchart", because exam answers are
    # clearer with decision flow + pseudocode/code.
    if answer_type == "algorithm":
        return {
            "visual_required": True,
            "visual_priority": "required",
            "visual_type": "Mermaid flowchart for algorithm logic",
            "preferred_visual_block": "mermaid",
            "why_visual_needed": "Algorithm questions require clear control-flow representation; a Mermaid flowchart shows initialization, decision, iteration, success, and failure paths.",
            "diagram_labels": ["Start", "Input", "Initialize", "Decision", "Compare", "Update Search Space", "Found", "Not Found", "End"],
            "image_search_query": f"{question} algorithm flowchart",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        }

    # Process/sequence/hierarchy often benefit from a visual, but remain recommended
    # unless an explicit or topic-specific mandatory rule matched above.
    if answer_type in {"process", "sequence", "hierarchy"}:
        return {
            "visual_required": False,
            "visual_priority": "recommended",
            "visual_type": "flowchart or structured table block",
            "why_visual_needed": "A structured visual block can improve clarity, but this question does not strictly require an external labelled diagram.",
            "diagram_labels": ["input", "process", "decision", "output"],
            "image_search_query": f"{question} flowchart educational diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        }

    return {
        "visual_required": False,
        "visual_priority": "optional",
        "visual_type": "simple conceptual diagram",
        "why_visual_needed": "A visual is not compulsory; the answer can be complete using structured explanation.",
        "diagram_labels": ["main concept", "important sub-points", "relationships"],
        "image_search_query": f"{question} educational diagram explanation",
        "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
    }

def normalize_visual_support(value: Any, question: str, answer_type: str) -> Dict[str, Any]:
    default = build_default_visual_support(question, answer_type)

    if not isinstance(value, dict):
        return default

    visual_required = value.get("visual_required")
    visual_required = visual_required if isinstance(visual_required, bool) else default["visual_required"]

    mandatory_topic_rule = get_mandatory_visual_topic_rule(question)
    recommended_topic_rule = get_recommended_visual_topic_rule(question)

    # Fix common bad analyzer behavior: comparison table marked as visual_required.
    visual_type_text = coerce_string(value.get("visual_type")).lower()
    if answer_type == "comparison" and not has_explicit_visual_request(question) and not mandatory_topic_rule:
        visual_required = False

    if answer_type == "comparison" and "table" in visual_type_text and not has_explicit_visual_request(question) and not mandatory_topic_rule:
        visual_required = False

    # Topic-specific mandatory visuals override weak LLM visual decisions.
    if mandatory_topic_rule or requires_mandatory_visual(question, answer_type):
        visual_required = True

    visual_priority = coerce_string(value.get("visual_priority")).lower()
    if visual_priority not in ALLOWED_VISUAL_PRIORITIES:
        visual_priority = default["visual_priority"]

    if visual_required:
        visual_priority = "required"
    elif answer_type == "comparison" and recommended_topic_rule:
        visual_priority = "recommended"
    elif answer_type == "comparison":
        visual_priority = "optional"

    websites = unique_list(
        coerce_string_list(value.get("recommended_websites"), default["recommended_websites"]),
        max_items=2,
    ) or DEFAULT_RECOMMENDED_WEBSITES

    if mandatory_topic_rule or recommended_topic_rule:
        default = build_default_visual_support(question, answer_type)

    return {
        "visual_required": visual_required,
        "visual_priority": visual_priority,
        "visual_type": coerce_string(value.get("visual_type")) or default["visual_type"],
        "why_visual_needed": coerce_string(value.get("why_visual_needed")) or default["why_visual_needed"],
        "diagram_labels": unique_list(coerce_string_list(value.get("diagram_labels"), default["diagram_labels"])),
        "image_search_query": coerce_string(value.get("image_search_query")) or default["image_search_query"],
        "recommended_websites": websites,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Block Plan Builders
# ─────────────────────────────────────────────────────────────────────────────

def base_required_points(title: str) -> List[str]:
    lowered = title.lower()
    if "introduction" in lowered or "definition" in lowered:
        return ["formal definition", "need or purpose", "basic principle"]
    if "comparison" in lowered or "difference" in lowered:
        return ["parameter-wise rows", "technical differences", "applications"]
    if "working" in lowered or "process" in lowered or "steps" in lowered:
        return ["ordered operation", "data/control flow", "technical explanation"]
    if "formula" in lowered or "derivation" in lowered:
        return ["formula", "symbols", "units", "assumptions", "final expression"]
    if "advantage" in lowered or "application" in lowered:
        return ["advantages with reasons", "real engineering applications", "limitations if relevant"]
    if "conclusion" in lowered:
        return ["summary", "engineering significance", "final exam-ready closing"]
    return ["technical explanation", "exam keywords", "relevant example"]


def make_block(
    block_type: str,
    title: str,
    purpose: str,
    points: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    block: Dict[str, Any] = {
        "type": block_type,
        "title": title,
        "purpose": purpose,
        "required_points": points or base_required_points(title),
    }
    block.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return remove_empty_values(block)


def build_intro_block(answer_type: str) -> Dict[str, Any]:
    if answer_type == "comparison":
        return make_block(
            "markdown",
            "Brief Introduction",
            "Define both compared concepts briefly in 3 to 5 sentences only.",
            ["short definition of both concepts", "common context", "basis of comparison"],
            max_words=120,
            rules=["do not add history unless asked", "do not add long background"],
        )

    return make_block(
        "markdown",
        "Introduction and Definition",
        "Introduce the concept, give a formal definition, and establish why it matters in engineering exams.",
        ["formal definition", "purpose", "core idea", "engineering relevance"],
    )


def build_image_block(visual_support: Dict[str, Any]) -> Dict[str, Any]:
    return make_block(
        "image",
        "Required Educational Diagram",
        "Provide the labelled diagram, graph, architecture, or visual support expected for full marks.",
        visual_support.get("diagram_labels", []),
        visual_type=visual_support.get("visual_type"),
        search_query=visual_support.get("image_search_query"),
        diagram_labels=visual_support.get("diagram_labels"),
        recommended_websites=visual_support.get("recommended_websites"),
    )


def build_comparison_plan(question: str, marks: int) -> List[Dict[str, Any]]:
    minimum_rows = min_table_rows_for_marks(marks)
    return [
        build_intro_block("comparison"),
        make_block(
            "table",
            "Difference / Comparison Table",
            "Compare both concepts parameter-wise using precise engineering differences.",
            [
                f"minimum {minimum_rows} parameter-wise rows",
                "technical basis of each difference",
                "applications if asked",
                "avoid generic one-word cells",
            ],
            suggested_columns=["Parameter", "First Concept", "Second Concept"],
            minimum_rows=minimum_rows,
            rules=[
                "each row must compare exactly one parameter",
                "do not use only two rows named after the concepts",
                "include examples/applications if requested by the question",
            ],
        ),
        make_block(
            "markdown",
            "Key Practical Difference",
            "Explain the most important practical difference briefly without repeating the full table.",
            ["when first concept is preferred", "when second concept is preferred", "one exam-focused observation"],
            max_words=180,
        ),
        make_block(
            "markdown",
            "Conclusion",
            "Give a short decision-oriented conclusion.",
            ["selection criteria", "engineering importance", "final statement"],
            max_words=100,
        ),
    ]


def _original_build_block_plan(question: str, answer_type: str, visual_support: Dict[str, Any], marks: int) -> List[Dict[str, Any]]:
    depth = depth_from_marks(marks)

    if answer_type == "comparison":
        plan = build_comparison_plan(question, marks)
        if visual_support.get("visual_required") or visual_support.get("visual_priority") == "recommended":
            image_block = build_image_block(visual_support)
            image_block["title"] = "Recommended Conceptual Visual" if not visual_support.get("visual_required") else image_block.get("title", "Required Educational Diagram")
            image_block["purpose"] = "Provide a helpful visual comparison without replacing the main comparison table."
            plan.insert(1, image_block)
        return plan

    plan: List[Dict[str, Any]] = []
    diagram_first = answer_type in {"image", "graph"} or has_explicit_visual_request(question)

    intro = build_intro_block(answer_type)
    image_block = build_image_block(visual_support)

    if diagram_first and visual_support.get("visual_required"):
        plan.extend([image_block, intro])
    else:
        plan.append(intro)
        if visual_support.get("visual_required"):
            plan.append(image_block)

    if answer_type in {"process", "sequence"}:
        plan.append(make_block(
            "steps",
            "Step-by-Step Working",
            "Explain the operation in correct sequence.",
            ["initial condition", "ordered stages", "data/control flow", "final result"],
            step_focus="working/process sequence",
            minimum_steps=min_steps_for_marks(marks),
        ))
        if marks >= 6:
            plan.append(make_block(
                "markdown",
                "Components and Technical Details",
                "Explain involved components and how they interact.",
                ["components", "interfaces", "signals/data", "examples"],
            ))

    elif answer_type == "hierarchy":
        plan.append(make_block(
            "table",
            "Layer-wise / Type-wise Explanation",
            "Present all layers, types, or categories with functions and examples.",
            ["all levels/types", "function of each", "examples", "relationship between levels"],
            suggested_columns=["Layer / Type", "Function", "Important Points", "Example"],
            minimum_rows=max(4, min_table_rows_for_marks(marks) - 2),
        ))
        plan.append(make_block(
            "steps",
            "Flow or Interaction Between Levels",
            "Explain how information, control, or dependency moves through the hierarchy.",
            ["top-down or bottom-up flow", "interaction", "practical example"],
            step_focus="interaction between layers/types",
            minimum_steps=min_steps_for_marks(marks),
        ))

    elif answer_type == "calculation":
        plan.append(make_block(
            "steps",
            "Numerical Solution Steps",
            "Solve in exam format: given data, formula, substitution, simplification, units, final answer.",
            ["given data", "formula", "substitution", "calculation", "unit", "final answer"],
            step_focus="calculation/derivation",
            minimum_steps=min_steps_for_marks(marks),
        ))
        plan.append(make_block(
            "markdown",
            "Result Interpretation",
            "Explain the meaning of the calculated result and mention units or assumptions.",
            ["final result meaning", "units", "assumptions", "reasonableness check"],
        ))

    elif answer_type == "formula":
        plan.append(make_block(
            "markdown",
            "Formula and Symbol Explanation",
            "State the required equation and explain every symbol and unit.",
            ["formula", "symbol meaning", "units", "conditions of use"],
        ))
        plan.append(make_block(
            "steps",
            "Derivation / Application Outline",
            "Show derivation or formula application in a clear sequence.",
            ["assumptions", "derivation steps", "final expression", "application"],
            step_focus="formula derivation/application",
            minimum_steps=min_steps_for_marks(marks),
        ))

    elif answer_type == "algorithm":
        plan.append(make_block(
            "mermaid",
            "Algorithm Flowchart",
            "Show the control flow of the algorithm using valid Mermaid flowchart syntax.",
            ["start", "input", "initialization", "decision", "iteration", "found/not found", "end"],
            diagram_type="flowchart",
            mermaid_requirements=[
                "content must start with flowchart TD",
                "include decision nodes",
                "show success and failure paths",
                "do not include explanation inside Mermaid content",
            ],
        ))
        plan.append(make_block(
            "steps",
            "Algorithm Steps",
            "Give clear algorithmic logic in ordered steps.",
            ["input", "initialization", "processing logic", "decision cases", "output"],
            step_focus="algorithm logic",
            minimum_steps=min_steps_for_marks(marks),
        ))
        plan.append(make_block(
            "code",
            "Pseudocode / Implementation",
            "Provide complete pseudocode or implementation even if the question only says explain algorithm.",
            ["input", "readable logic", "comments", "edge cases", "output"],
            language_hint="pseudocode",
            code_requirements=["complete pseudocode", "initialization", "loop/recursion", "decision handling", "return value", "complexity explanation"],
            mandatory=True,
        ))
        plan.append(make_block(
            "markdown",
            "Complexity Analysis",
            "Mention time and space complexity with reason.",
            ["best case", "worst case", "average case", "space complexity", "reason"],
        ))

    elif answer_type == "code":
        plan.append(make_block(
            "code",
            "Program / Implementation",
            "Write complete exam-suitable code with comments.",
            ["input", "logic", "output", "comments", "edge cases"],
            language_hint="infer from question/context",
            code_requirements=["complete code", "clear variable names", "sample output", "brief explanation"],
        ))
        plan.append(make_block(
            "markdown",
            "Code Explanation",
            "Explain the logic, important statements, and output.",
            ["logic explanation", "important functions", "sample output", "complexity if relevant"],
        ))

    elif answer_type == "graph":
        plan.append(make_block(
            "markdown",
            "Graph / Waveform Explanation",
            "Explain axes, curve nature, regions, and interpretation.",
            ["x-axis", "y-axis", "shape of curve", "important regions", "interpretation"],
        ))

    elif answer_type == "timeline":
        plan.append(make_block(
            "table",
            "Chronological Development",
            "Present evolution or phases in chronological order.",
            ["phase/year", "development", "technical significance"],
            suggested_columns=["Phase / Period", "Development", "Technical Significance"],
            minimum_rows=max(4, min_table_rows_for_marks(marks) - 2),
        ))

    elif answer_type == "image":
        plan.append(make_block(
            "markdown",
            "Diagram Explanation",
            "Explain every important label and its function.",
            ["label explanation", "component function", "working/significance"],
        ))

    else:
        plan.append(make_block(
            "markdown",
            "Detailed Technical Explanation",
            "Explain the main concept with technical depth and examples.",
            ["principle", "working", "components", "examples", "importance"],
        ))

    if marks >= 6 and answer_type not in {"calculation", "code", "formula"}:
        plan.append(make_block(
            "markdown",
            "Advantages, Limitations and Applications",
            "Cover merits, limitations, and real engineering applications.",
            ["advantages with reasons", "limitations", "applications", "industry examples"],
        ))

    if depth in {"detailed", "exhaustive"} and answer_type not in {"comparison", "calculation"}:
        plan.append(make_block(
            "markdown",
            "Exam-Focused Points",
            "Add scoring keywords, common mistakes, and concise observations useful for full marks.",
            ["scoring keywords", "important observations", "common mistakes to avoid"],
        ))

    plan.append(make_block(
        "markdown",
        "Conclusion",
        "End with a compact conclusion that restates significance without repeating the whole answer.",
        ["concept summary", "engineering importance", "final statement"],
        max_words=140,
    ))

    return plan


def normalize_block_plan(
    block_plan: Any,
    question: str,
    answer_type: str,
    visual_support: Dict[str, Any],
    marks: int,
) -> List[Dict[str, Any]]:
    # For comparison, always rebuild to avoid bad table/image plans from the model.
    if answer_type == "comparison":
        return build_block_plan(question, answer_type, visual_support, marks)

    if not isinstance(block_plan, list) or not block_plan:
        return build_block_plan(question, answer_type, visual_support, marks)

    normalized: List[Dict[str, Any]] = []

    for item in block_plan:
        if not isinstance(item, dict):
            continue

        block_type = coerce_string(item.get("type")).lower()
        if block_type not in ALLOWED_BLOCK_TYPES:
            continue

        # Remove image block if visual is not required and it is likely unnecessary.
        if block_type == "image" and not visual_support.get("visual_required"):
            continue

        title = coerce_string(item.get("title")) or block_type.title()
        purpose = coerce_string(item.get("purpose")) or f"Generate a {block_type} block for {title}."
        required_points = unique_list(coerce_string_list(item.get("required_points"), base_required_points(title)))

        block: Dict[str, Any] = {
            "type": block_type,
            "title": title,
            "purpose": purpose,
            "required_points": required_points,
        }

        for key in (
            "suggested_columns", "minimum_rows", "visual_type", "search_query",
            "diagram_labels", "recommended_websites", "step_focus", "minimum_steps",
            "language_hint", "code_requirements", "rules", "max_words",
        ):
            if key in item:
                block[key] = item[key]

        normalized.append(remove_empty_values(block))

    return normalized or build_block_plan(question, answer_type, visual_support, marks)

# ─────────────────────────────────────────────────────────────────────────────
# Analysis Validation
# ─────────────────────────────────────────────────────────────────────────────

def default_structure_for_type(answer_type: str) -> List[str]:
    mapping = {
        "comparison": ["Brief Introduction", "Comparison Table", "Key Difference", "Conclusion"],
        "process": ["Introduction", "Diagram/Flowchart", "Step-wise Working", "Components", "Applications", "Conclusion"],
        "sequence": ["Introduction", "Ordered Sequence", "Explanation", "Conclusion"],
        "hierarchy": ["Introduction", "Diagram", "Layer/Type-wise Explanation", "Interaction", "Applications", "Conclusion"],
        "graph": ["Introduction", "Graph", "Axes", "Curve Explanation", "Conclusion"],
        "timeline": ["Introduction", "Chronological Table", "Significance", "Conclusion"],
        "formula": ["Introduction", "Formula", "Symbols", "Derivation/Application", "Conclusion"],
        "calculation": ["Given Data", "Formula", "Substitution", "Solution", "Final Answer"],
        "algorithm": ["Introduction", "Algorithm Steps", "Pseudocode", "Complexity", "Conclusion"],
        "code": ["Program", "Explanation", "Output", "Complexity"],
        "image": ["Diagram", "Labels", "Explanation", "Conclusion"],
        "text": ["Introduction", "Definition", "Detailed Explanation", "Applications", "Conclusion"],
    }
    return mapping.get(answer_type, mapping["text"])


def validate_answer_strategy(strategy: Any, answer_type: str, question: str) -> Dict[str, Any]:
    default = infer_answer_strategy(answer_type, question)
    if not isinstance(strategy, dict):
        return default

    merged = {
        "opening_style": coerce_string(strategy.get("opening_style")) or default["opening_style"],
        "explanation_style": coerce_string(strategy.get("explanation_style")) or default["explanation_style"],
        "exam_orientation": coerce_string(strategy.get("exam_orientation")) or default["exam_orientation"],
        "avoid": unique_list(coerce_string_list(strategy.get("avoid"), default["avoid"])),
    }

    # Add hard avoid rules for comparison regardless of LLM output.
    if answer_type == "comparison":
        merged["avoid"] = unique_list(merged["avoid"] + infer_answer_strategy(answer_type, question)["avoid"])

    return merged


def validate_analysis_json(parsed: Dict[str, Any], question: str, marks: int) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}

    inferred_type = infer_answer_type(question)
    answer_type = coerce_string(parsed.get("answer_type")).lower()

    if answer_type not in ALLOWED_ANSWER_TYPES:
        answer_type = inferred_type

    # Prefer deterministic inference when the model misses strong signals.
    if inferred_type in {"comparison", "code", "algorithm", "calculation", "formula"}:
        answer_type = inferred_type

    difficulty = coerce_string(parsed.get("difficulty")).lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = difficulty_from_marks(marks)

    depth_level = coerce_string(parsed.get("depth_level")).lower()
    if depth_level not in {"short", "medium", "detailed", "exhaustive"}:
        depth_level = depth_from_marks(marks)

    visual_support = normalize_visual_support(parsed.get("visual_support"), question, answer_type)
    strategy = validate_answer_strategy(parsed.get("answer_strategy"), answer_type, question)

    must_include = unique_list(
        coerce_string_list(parsed.get("must_include"), [])
        + GENERIC_SCORING_KEYWORDS.get(answer_type, []),
        max_items=14,
    )

    scoring_keywords = unique_list(
        coerce_string_list(parsed.get("scoring_keywords"), [])
        + GENERIC_SCORING_KEYWORDS.get(answer_type, []),
        max_items=16,
    )

    result: Dict[str, Any] = {
        "answer_type": answer_type,
        "question_intent": coerce_string(parsed.get("question_intent")) or f"Prepare a full-mark engineering exam answer for: {question}",
        "difficulty": difficulty,
        "depth_level": depth_level,
        "marks": marks,
        "full_marks_answer_structure": unique_list(
            coerce_string_list(parsed.get("full_marks_answer_structure"), default_structure_for_type(answer_type))
        ),
        "must_include": must_include or GENERIC_SCORING_KEYWORDS.get(answer_type, ["definition", "technical explanation", "example", "conclusion"]),
        "scoring_keywords": scoring_keywords,
        "examiner_focus": unique_list(
            coerce_string_list(parsed.get("examiner_focus"), ["clarity", "technical correctness", "complete structure"]),
            max_items=10,
        ),
        "answer_strategy": strategy,
        "visual_support": visual_support,
    }

    result["block_plan"] = normalize_block_plan(
        parsed.get("block_plan"), question, answer_type, visual_support, marks
    )

    return remove_empty_values(result)

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_question(
    question: str,
    branch: Optional[str] = None,
    subject: Optional[str] = None,
    unit: Optional[str] = None,
    marks: Optional[str | int] = None,
    syllabus: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze an engineering exam question and return a dynamic answer blueprint.
    This function never generates the final answer.
    """
    question = coerce_string(question)
    if not question:
        raise ValueError("Question is required")

    marks_int = coerce_int(marks, default=8)

    prompt = USER_PROMPT_TEMPLATE.format(
        question=question,
        branch=coerce_string(branch) or "Not provided",
        subject=coerce_string(subject) or "Not provided",
        unit=coerce_string(unit) or "Not provided",
        marks=marks_int,
        syllabus=coerce_string(syllabus) or "Not provided",
    )

    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.12,
        )
        parsed = clean_json_response(raw)
    except Exception as exc:
        logger.warning("Question analysis failed; using deterministic fallback: %s", exc)
        parsed = {
            "answer_type": infer_answer_type(question),
            "question_intent": f"Prepare a full-mark engineering exam answer for: {question}",
        }

    return validate_analysis_json(parsed, question, marks_int)


# ─────────────────────────────────────────────────────────────────────────────
# Dev Smoke Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # This does not call OpenRouter; it only tests deterministic validation/building.
    sample_question = "Differentiate between TCP and UDP protocols with respect to reliability, connection setup, speed, error control, and applications."
    sample = validate_analysis_json({}, sample_question, 8)
    print(json.dumps(sample, indent=2, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────────────────────
# FINAL OVERRIDES: Mandatory Image Support for Every Engineering Question
# ─────────────────────────────────────────────────────────────────────────────
# Existing analyzer behavior is preserved. These overrides only strengthen visual
# planning so every final answer has at least one image block that the existing
# SerpAPI image fetcher can resolve using search_query.

ALWAYS_REQUIRE_IMAGE_BLOCK = True
MAX_ANALYZER_IMAGE_BLOCKS = 3
_IMAGE_PLACEMENT_AFTER_INTRO = "after_introduction"
_IMAGE_PLACEMENT_BEFORE_TABLE = "before_table"
_IMAGE_PLACEMENT_BEFORE_STEPS = "before_steps"
_IMAGE_PLACEMENT_START = "start"


def _keyword_in_question(question: str, *keywords: str) -> bool:
    q = f" {question.lower()} "
    return any(keyword.lower() in q for keyword in keywords)


def _primary_image_blueprint(question: str, answer_type: str) -> Dict[str, Any]:
    """Return the best single image blueprint for any engineering question."""
    mandatory_topic_rule = get_mandatory_visual_topic_rule(question) or {}
    recommended_topic_rule = get_recommended_visual_topic_rule(question) or {}

    if mandatory_topic_rule:
        return {
            "type": "image",
            "title": mandatory_topic_rule.get("title") or mandatory_topic_rule.get("visual_type") or "Required Educational Diagram",
            "visual_type": mandatory_topic_rule.get("visual_type", "required educational diagram"),
            "search_query": mandatory_topic_rule.get("image_search_query", f"{question} labelled educational diagram"),
            "image_search_query": mandatory_topic_rule.get("image_search_query", f"{question} labelled educational diagram"),
            "recommended_websites": list(mandatory_topic_rule.get("recommended_websites", DEFAULT_RECOMMENDED_WEBSITES))[:2] or DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": list(mandatory_topic_rule.get("diagram_labels", [])) or ["main concept", "process", "output"],
            "why_visual_needed": mandatory_topic_rule.get("why_visual_needed", "A topic-specific visual improves full-mark presentation."),
            "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    if recommended_topic_rule:
        return {
            "type": "image",
            "title": recommended_topic_rule.get("title") or "Conceptual Visual Comparison",
            "visual_type": recommended_topic_rule.get("visual_type", "conceptual educational visual"),
            "search_query": recommended_topic_rule.get("image_search_query", f"{question} conceptual visual diagram"),
            "image_search_query": recommended_topic_rule.get("image_search_query", f"{question} conceptual visual diagram"),
            "recommended_websites": list(recommended_topic_rule.get("recommended_websites", DEFAULT_RECOMMENDED_WEBSITES))[:2] or DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": list(recommended_topic_rule.get("diagram_labels", [])) or ["main concept", "comparison", "example"],
            "why_visual_needed": recommended_topic_rule.get("why_visual_needed", "A conceptual visual improves clarity and exam presentation."),
            "placement": _IMAGE_PLACEMENT_BEFORE_TABLE if answer_type == "comparison" else _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    if answer_type == "comparison":
        return {
            "type": "image",
            "title": "Conceptual Comparison Diagram",
            "visual_type": "conceptual comparison diagram",
            "search_query": f"{question} conceptual comparison diagram",
            "image_search_query": f"{question} conceptual comparison diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": ["Concept 1", "Concept 2", "Key difference", "Example"],
            "why_visual_needed": "Every engineering answer includes one visual block; this supports the comparison without replacing the table.",
            "placement": _IMAGE_PLACEMENT_BEFORE_TABLE,
        }

    if answer_type == "algorithm" or _keyword_in_question(question, "algorithm", "pseudocode", "binary search", "sorting"):
        return {
            "type": "image",
            "title": "Algorithm Flowchart Diagram",
            "visual_type": "algorithm flowchart diagram",
            "search_query": f"{question} algorithm flowchart diagram",
            "image_search_query": f"{question} algorithm flowchart diagram",
            "recommended_websites": ["GeeksforGeeks", "Programiz"],
            "diagram_labels": ["Start", "Input", "Initialize", "Decision", "Process", "Output", "End"],
            "why_visual_needed": "A flowchart image represents algorithm control flow clearly for exam answers.",
            "placement": _IMAGE_PLACEMENT_BEFORE_STEPS,
        }

    if answer_type == "code" or _keyword_in_question(question, "program", "code", "implementation"):
        return {
            "type": "image",
            "title": "Program Logic Flow Diagram",
            "visual_type": "program logic flow diagram",
            "search_query": f"{question} program logic flowchart",
            "image_search_query": f"{question} program logic flowchart",
            "recommended_websites": ["GeeksforGeeks", "Programiz"],
            "diagram_labels": ["Input", "Processing", "Decision", "Output"],
            "why_visual_needed": "A flow diagram supports code understanding before implementation.",
            "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    if answer_type in {"process", "sequence"} or _keyword_in_question(question, "steps", "process", "working", "workflow", "lifecycle"):
        return {
            "type": "image",
            "title": "Process / Workflow Diagram",
            "visual_type": "process workflow diagram",
            "search_query": f"{question} workflow process diagram",
            "image_search_query": f"{question} workflow process diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": ["Input", "Process", "Decision", "Output", "Feedback"],
            "why_visual_needed": "A workflow diagram presents the ordered process clearly.",
            "placement": _IMAGE_PLACEMENT_BEFORE_STEPS,
        }

    if answer_type in {"hierarchy", "image"} or _keyword_in_question(question, "architecture", "model", "layers", "components", "structure"):
        return {
            "type": "image",
            "title": "Architecture / Model Diagram",
            "visual_type": "architecture or model diagram",
            "search_query": f"{question} labelled architecture model diagram",
            "image_search_query": f"{question} labelled architecture model diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": ["Main components", "Layers", "Connections", "Flow"],
            "why_visual_needed": "Architecture/model questions are clearer with labelled visual structure.",
            "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    if answer_type == "graph" or _keyword_in_question(question, "graph", "curve", "waveform", "characteristics"):
        return {
            "type": "image",
            "title": "Graph / Characteristics Diagram",
            "visual_type": "graph or characteristics diagram",
            "search_query": f"{question} graph characteristics diagram",
            "image_search_query": f"{question} graph characteristics diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": ["X-axis", "Y-axis", "Curve", "Important regions"],
            "why_visual_needed": "Graph-based questions need visual interpretation of axes and curve behavior.",
            "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    if answer_type in {"calculation", "formula"}:
        return {
            "type": "image",
            "title": "Formula / Concept Support Diagram",
            "visual_type": "formula or concept support diagram",
            "search_query": f"{question} formula concept diagram",
            "image_search_query": f"{question} formula concept diagram",
            "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
            "diagram_labels": ["Given quantities", "Formula", "Relationship", "Result"],
            "why_visual_needed": "A formula/concept diagram helps explain the relationship used in the solution.",
            "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
        }

    return {
        "type": "image",
        "title": "Educational Concept Diagram",
        "visual_type": "educational concept diagram",
        "search_query": f"{question} educational concept diagram",
        "image_search_query": f"{question} educational concept diagram",
        "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
        "diagram_labels": ["Main concept", "Important parts", "Relationship", "Example"],
        "why_visual_needed": "Every engineering answer includes one visual block for better presentation and understanding.",
        "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
    }


def build_mandatory_image_blueprints(question: str, answer_type: str) -> List[Dict[str, Any]]:
    """Build one or more image blueprints. Multiple images are used only when useful."""
    images: List[Dict[str, Any]] = [_primary_image_blueprint(question, answer_type)]
    q = question.lower()

    if ("diagram" in q or "draw" in q) and any(word in q for word in ("flowchart", "graph", "waveform", "curve")):
        if "flowchart" in q:
            images.append({
                "type": "image",
                "title": "Flowchart Diagram",
                "visual_type": "flowchart diagram",
                "search_query": f"{question} flowchart diagram",
                "image_search_query": f"{question} flowchart diagram",
                "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
                "diagram_labels": ["Start", "Process", "Decision", "Output", "End"],
                "why_visual_needed": "The question explicitly expects flowchart-style visual support.",
                "placement": _IMAGE_PLACEMENT_BEFORE_STEPS,
            })
        if any(word in q for word in ("graph", "waveform", "curve")):
            images.append({
                "type": "image",
                "title": "Graph / Waveform Diagram",
                "visual_type": "graph or waveform diagram",
                "search_query": f"{question} graph waveform diagram",
                "image_search_query": f"{question} graph waveform diagram",
                "recommended_websites": DEFAULT_RECOMMENDED_WEBSITES,
                "diagram_labels": ["X-axis", "Y-axis", "Curve/Waveform", "Important points"],
                "why_visual_needed": "The question explicitly expects graph/waveform support.",
                "placement": _IMAGE_PLACEMENT_AFTER_INTRO,
            })

    unique: List[Dict[str, Any]] = []
    seen = set()
    for img in images:
        key = (coerce_string(img.get("search_query") or img.get("image_search_query")) or coerce_string(img.get("title"))).lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(img)
    return unique[:MAX_ANALYZER_IMAGE_BLOCKS]


def build_default_visual_support(question: str, answer_type: str) -> Dict[str, Any]:
    images = build_mandatory_image_blueprints(question, answer_type)
    primary = images[0]
    return remove_empty_values({
        "visual_required": True,
        "visual_priority": "required",
        "visual_type": primary.get("visual_type", "educational diagram"),
        "why_visual_needed": primary.get("why_visual_needed", "Every engineering answer must include at least one visual block."),
        "diagram_labels": primary.get("diagram_labels", ["main concept", "important labels"]),
        "image_search_query": primary.get("image_search_query") or primary.get("search_query") or f"{question} educational diagram",
        "recommended_websites": list(primary.get("recommended_websites", DEFAULT_RECOMMENDED_WEBSITES))[:2] or DEFAULT_RECOMMENDED_WEBSITES,
        "preferred_visual_block": "image",
        "placement": primary.get("placement", _IMAGE_PLACEMENT_AFTER_INTRO),
        "minimum_images": 1,
        "image_blocks": images,
    })


def normalize_visual_support(value: Any, question: str, answer_type: str) -> Dict[str, Any]:
    default = build_default_visual_support(question, answer_type)
    if not isinstance(value, dict):
        return default

    model_query = coerce_string(value.get("image_search_query"))
    model_visual_type = coerce_string(value.get("visual_type"))
    if model_query and "table" not in model_query.lower() and len(model_query.split()) >= 3:
        default["image_search_query"] = model_query
        default["image_blocks"][0]["search_query"] = model_query
        default["image_blocks"][0]["image_search_query"] = model_query
    if model_visual_type and "table" not in model_visual_type.lower():
        default["visual_type"] = model_visual_type
        default["image_blocks"][0]["visual_type"] = model_visual_type

    labels = coerce_string_list(value.get("diagram_labels"), [])
    if labels and not any("table" in label.lower() for label in labels):
        default["diagram_labels"] = unique_list(labels)
        default["image_blocks"][0]["diagram_labels"] = unique_list(labels)

    websites = unique_list(coerce_string_list(value.get("recommended_websites"), default["recommended_websites"]), max_items=2)
    default["recommended_websites"] = websites or DEFAULT_RECOMMENDED_WEBSITES
    default["image_blocks"][0]["recommended_websites"] = default["recommended_websites"]

    default["visual_required"] = True
    default["visual_priority"] = "required"
    default["preferred_visual_block"] = "image"
    default["minimum_images"] = max(1, int(default.get("minimum_images", 1)))
    return remove_empty_values(default)


def build_image_block(visual_support: Dict[str, Any]) -> Dict[str, Any]:
    image_blocks = visual_support.get("image_blocks") if isinstance(visual_support, dict) else None
    source = image_blocks[0] if isinstance(image_blocks, list) and image_blocks and isinstance(image_blocks[0], dict) else visual_support
    return make_block(
        "image",
        coerce_string(source.get("title")) or coerce_string(source.get("visual_type")) or "Required Educational Diagram",
        "Provide the required educational image block. The backend fetcher resolves the URL using search_query.",
        source.get("diagram_labels", visual_support.get("diagram_labels", [])),
        visual_type=source.get("visual_type", visual_support.get("visual_type")),
        search_query=source.get("search_query") or source.get("image_search_query") or visual_support.get("image_search_query"),
        diagram_labels=source.get("diagram_labels", visual_support.get("diagram_labels")),
        recommended_websites=source.get("recommended_websites", visual_support.get("recommended_websites")),
        placement=source.get("placement", visual_support.get("placement", _IMAGE_PLACEMENT_AFTER_INTRO)),
        mandatory=True,
    )


def build_image_blocks(visual_support: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_images = visual_support.get("image_blocks") if isinstance(visual_support, dict) else None
    if not isinstance(raw_images, list) or not raw_images:
        return [build_image_block(visual_support)]
    blocks: List[Dict[str, Any]] = []
    for raw in raw_images[:MAX_ANALYZER_IMAGE_BLOCKS]:
        if not isinstance(raw, dict):
            continue
        block = make_block(
            "image",
            coerce_string(raw.get("title")) or coerce_string(raw.get("visual_type")) or "Required Educational Diagram",
            "Provide the required educational image block. The backend fetcher resolves the URL using search_query.",
            raw.get("diagram_labels", visual_support.get("diagram_labels", [])),
            visual_type=raw.get("visual_type", visual_support.get("visual_type")),
            search_query=raw.get("search_query") or raw.get("image_search_query") or visual_support.get("image_search_query"),
            diagram_labels=raw.get("diagram_labels", visual_support.get("diagram_labels")),
            recommended_websites=raw.get("recommended_websites", visual_support.get("recommended_websites")),
            placement=raw.get("placement", visual_support.get("placement", _IMAGE_PLACEMENT_AFTER_INTRO)),
            mandatory=True,
        )
        blocks.append(block)
    return blocks or [build_image_block(visual_support)]


def _insert_image_blocks_after_intro(plan: List[Dict[str, Any]], image_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not image_blocks:
        return plan
    for i, item in enumerate(plan):
        if item.get("type") == "table":
            return plan[:i] + image_blocks + plan[i:]
    for i, item in enumerate(plan):
        if item.get("type") == "markdown" and any(token in coerce_string(item.get("title")).lower() for token in ("intro", "definition")):
            return plan[: i + 1] + image_blocks + plan[i + 1:]
    return image_blocks + plan


def build_block_plan(question: str, answer_type: str, visual_support: Dict[str, Any], marks: int) -> List[Dict[str, Any]]:
    plan = _original_build_block_plan(question, answer_type, visual_support, marks)
    existing_queries = {
        coerce_string(item.get("search_query")).lower()
        for item in plan
        if isinstance(item, dict) and item.get("type") == "image"
    }
    missing_images = [
        img for img in build_image_blocks(visual_support)
        if coerce_string(img.get("search_query")).lower() not in existing_queries
    ]
    if missing_images:
        plan = _insert_image_blocks_after_intro(plan, missing_images)
    return plan


def normalize_block_plan(block_plan: Any, question: str, answer_type: str, visual_support: Dict[str, Any], marks: int) -> List[Dict[str, Any]]:
    # Always rebuild so placement and required image blocks stay deterministic.
    return build_block_plan(question, answer_type, visual_support, marks)


SYSTEM_PROMPT = SYSTEM_PROMPT + """

FINAL VISUAL POLICY — STRICT:
Every engineering answer blueprint must include at least one image block.
Set visual_support.visual_required=true and visual_priority="required" for every question.
The image block is only a fetch blueprint; never generate or include image URLs.
For multiple visuals explicitly required, include multiple image blocks in visual_support.image_blocks and block_plan.
"""

USER_PROMPT_TEMPLATE = USER_PROMPT_TEMPLATE.replace(
    "7. For comparison questions, visual_support should usually be optional because the required comparison table is a table block, not an image.",
    "7. For every question, visual_support must be required because the backend image fetcher will resolve an educational image from search_query. Comparison questions still need a table, but must also include a supporting conceptual image block."
)
