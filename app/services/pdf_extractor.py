import os
import re
import json
import fitz
import cv2
import numpy as np
import cloudinary
import cloudinary.uploader
from io import BytesIO
from dotenv import load_dotenv

from app.services.ai.gemini_client import fix_pdf_math_with_vision

load_dotenv()

# =========================
# CONFIG
# =========================

TEMP_DIR = "temp_extracted_diagrams"

# Direct Cloudinary config
# Let's try to pull from env vars if available, else use placeholders
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "dxuvv6owm")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "YOUR_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "YOUR_API_SECRET")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

# =========================
# REGEX PATTERNS
# =========================

MAIN_SUB_RE = re.compile(r"^\s*(?:Q\s*\.?)?\s*(\d{1,2})\s*[\.\)]\s*(?:([a-hj-uw-yz])\s*\))?\s*(.*)", re.I)
SUB_RE = re.compile(r"^\s*(?:Q\s*\.?)?\s*([a-hj-uw-yz])\s*\)\s*(.*)", re.I)
OR_RE = re.compile(r"^\s*OR\s*$", re.I)

BAD_LINE_PATTERNS = [
    r"^GUG/[A-Z]/\d+/\d+.*$",
    r"^\*+$",
    r"^P\.T\.O$",
    r"^B\.E\.",
    r"^B\.Tech",
    r"^ESC\d+",
    r"^BE\d+[a-zA-Z]+",
    r"^P\. Pages",
    r"^Time\s*:",
    r"^Max\. Marks",
    r"^Notes\s*:",
]

# =========================
# TEXT CLEANING
# =========================

# Mapping for common PDF PUA (Private Use Area) characters that correspond to the Adobe Symbol font.
PUA_SYMBOL_MAP = {
    "\uf022": "∀", "\uf024": "∃", "\uf02A": "∗", "\uf02D": "−",
    "\uf040": "≅", "\uf041": "Α", "\uf042": "Β", "\uf043": "Χ",
    "\uf044": "Δ", "\uf045": "Ε", "\uf046": "Φ", "\uf047": "Γ",
    "\uf048": "Η", "\uf049": "Ι", "\uf04A": "ϑ", "\uf04B": "Κ",
    "\uf04C": "Λ", "\uf04D": "Μ", "\uf04E": "Ν", "\uf04F": "Ο",
    "\uf050": "Π", "\uf051": "Θ", "\uf052": "Ρ", "\uf053": "Σ",
    "\uf054": "Τ", "\uf055": "Υ", "\uf056": "ς", "\uf057": "Ω",
    "\uf058": "Ξ", "\uf059": "Ψ", "\uf05A": "Ζ", "\uf05C": "∴",
    "\uf05E": "⊥", "\uf061": "α", "\uf062": "β", "\uf063": "χ",
    "\uf064": "δ", "\uf065": "ε", "\uf066": "φ", "\uf067": "γ",
    "\uf068": "η", "\uf069": "ι", "\uf06A": "ϕ", "\uf06B": "κ",
    "\uf06C": "λ", "\uf06D": "μ", "\uf06E": "ν", "\uf06F": "ο",
    "\uf070": "π", "\uf071": "θ", "\uf072": "ρ", "\uf073": "σ",
    "\uf074": "τ", "\uf075": "υ", "\uf076": "ϖ", "\uf077": "ω",
    "\uf078": "ξ", "\uf079": "ψ", "\uf07A": "ζ",
    
    # Also add the standard Omega symbol that sometimes gets extracted as Ohm
    "Ω": "Ω",
}

def clean_text(text: str) -> str:
    # Translate PUA symbols to actual Unicode math/greek symbols
    for pua_char, unicode_char in PUA_SYMBOL_MAP.items():
        text = text.replace(pua_char, unicode_char)
    
    # Remove watermarks
    text = re.sub(r"Kabir\s*\(Aditya\s*Rathod\)?", "", text, flags=re.I)
    text = re.sub(r"Kabir\s*\(Aditya", "", text, flags=re.I)
    
    text = " ".join(text.split()).strip()

    for pattern in BAD_LINE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.I).strip()

    text = re.sub(r"GUG/[A-Z]/\d+/\d+\s*\d*", "", text, flags=re.I)
    text = re.sub(r"\bP\.T\.O\b", "", text, flags=re.I)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text

def is_bad_line(text: str, has_mark: bool = False) -> bool:
    text_lower = text.lower()
    if "time : " in text_lower or "max. marks" in text_lower:
        return True
    if text_lower.startswith("notes :"):
        return True
    
    note_phrases = [
        "all questions carry",
        "illustrate your answers wherever necessary",
        "all questions are compulsory",
        "due credit will be given",
        "assume suitable data",
        "use of slide rule",
        "non programmable",
        "thermodynamic tables for moist air",
        "wherever necessary",
        "diagrams and chemical equation",
    ]
    for phrase in note_phrases:
        if phrase in text_lower:
            return True

    text = clean_text(text)

    if not text:
        return not has_mark

    if re.fullmatch(r"\d+", text):
        return True

    # Strip leading question number just for bad line check so patterns can match
    text_no_num = re.sub(r"^(?:Q\s*\.?)?\s*\d{1,2}\s*[\.\)]\s*(?:[a-hj-uw-yz]\s*\))?\s*", "", text, flags=re.I)

    for pattern in BAD_LINE_PATTERNS:
        if re.match(pattern, text_no_num, flags=re.I):
            return True

    return False

# =========================
# CLOUDINARY
# =========================

def upload_to_cloudinary(image_path: str) -> str:
    result = cloudinary.uploader.upload(
        image_path,
        folder="question_paper_diagrams",
        resource_type="image",
    )
    return result["secure_url"]

def upload_bytes_to_cloudinary(image_bytes: bytes) -> str:
    result = cloudinary.uploader.upload(
        image_bytes,
        folder="question_paper_diagrams",
        resource_type="image",
    )
    return result["secure_url"]

def delete_image_from_cloudinary(image_url: str) -> bool:
    try:
        # Extract public_id from the Cloudinary URL.
        # URLs look like: https://res.cloudinary.com/cloud_name/image/upload/v12345/folder/filename.png
        # We need "folder/filename" without extension.
        parts = image_url.split("/upload/")
        if len(parts) == 2:
            # Remove version if present
            path = parts[1]
            if path.startswith("v") and "/" in path:
                # v123456/folder/filename.png -> folder/filename.png
                parts2 = path.split("/", 1)
                if parts2[0][1:].isdigit():
                    path = parts2[1]
            
            # Remove extension
            public_id = path.rsplit(".", 1)[0]
            cloudinary.uploader.destroy(public_id)
            return True
        return False
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to delete image {image_url}: {e}")
        return False

def upload_raw_pdf_to_cloudinary(pdf_bytes: bytes, filename: str) -> str:
    file_obj = BytesIO(pdf_bytes)
    file_obj.name = filename  # Give it a name so Cloudinary knows it's a .pdf
    result = cloudinary.uploader.upload(
        file_obj,
        folder="question_papers",
        resource_type="raw",
    )
    return result["secure_url"]

# =========================
# PDF TEXT LINE EXTRACTION
# =========================

def get_page_lines(page, page_diagrams):
    words = page.get_text("words")
    page_w = page.rect.width
    page_h = page.rect.height

    rows = {}

    for word in words:
        x0, y0, x1, y1, text, *_ = word

        # Header/footer ignore
        if y0 < 35 or y0 > page_h - 35:
            continue

        # Ignore words that are inside any diagram
        inside_diagram = False
        for diagram in page_diagrams:
            dx0, dy0, dx1, dy1 = diagram["bbox"]
            # Check if the center of the word falls inside the diagram
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            if dx0 <= cx <= dx1 and dy0 <= cy <= dy1:
                inside_diagram = True
                break
        
        if inside_diagram:
            continue

        row_key = round(y0 / 4) * 4
        rows.setdefault(row_key, []).append((x0, y0, x1, y1, text))

    lines = []

    for _, row in sorted(rows.items()):
        row = sorted(row, key=lambda x: x[0])

        mark = None
        text_words = []

        for x0, y0, x1, y1, text in row:
            # Right side marks detection
            if x0 > page_w * 0.82 and text.isdigit():
                mark = int(text)
                continue

            text_words.append(text)

        text = clean_text(" ".join(text_words))

        if is_bad_line(text, has_mark=(mark is not None)):
            continue

        x0 = min(w[0] for w in row)
        y0 = min(w[1] for w in row)
        x1 = max(w[2] for w in row)
        y1 = max(w[3] for w in row)

        lines.append({
            "text": text,
            "mark": mark,
            "bbox": [x0, y0, x1, y1],
        })

    return lines

# =========================
# QUESTION EXTRACTION
# =========================

def extract_questions_from_lines(lines, page_width):
    questions = []
    current = None
    current_main = None
    or_before = False

    def save_current():
        nonlocal current
        if current:
            current["question"] = clean_text(current["question"])
            if current["question"]:
                questions.append(current)
            current = None

    for line in lines:
        text = line["text"]
        bbox = line["bbox"]
        mark = line["mark"]
        page_number = line["page"]

        if OR_RE.match(text):
            save_current()
            or_before = True
            continue

        main_match = MAIN_SUB_RE.match(text)
        sub_match = SUB_RE.match(text)

        if main_match:
            save_current()

            current_main = main_match.group(1)
            sub = (main_match.group(2) or "").lower()
            q_text = clean_text(main_match.group(3))

            current = {
                "page": page_number,
                "question_no": current_main,
                "sub_question": sub,
                "question_key": f"{current_main}{sub}",
                "question": q_text,
                "marks": mark,
                "has_or_before": or_before,
                "image_urls": [],
                "_bbox": bbox,
            }

            or_before = False
            continue

        if sub_match and current_main:
            save_current()

            sub = sub_match.group(1).lower()
            q_text = clean_text(sub_match.group(2))

            current = {
                "page": page_number,
                "question_no": current_main,
                "sub_question": sub,
                "question_key": f"{current_main}{sub}",
                "question": q_text,
                "marks": mark,
                "has_or_before": or_before,
                "image_urls": [],
                "_bbox": bbox,
            }

            or_before = False
            continue

        if current:
            current["question"] += " " + text
            current["_bbox"][2] = max(current["_bbox"][2], bbox[2])
            current["_bbox"][3] = bbox[3]

            if mark is not None:
                current["marks"] = mark

    save_current()
    return questions

# =========================
# DIAGRAM EXTRACTION
# =========================

def extract_diagrams_from_page(page, page_number: int, temp_dir: str):
    zoom = 4
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

    image = np.frombuffer(pix.samples, dtype=np.uint8)
    image = image.reshape(pix.height, pix.width, 3)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    _, binary = cv2.threshold(
        gray,
        210,  # Increased from 180 to catch lighter diagrams
        255,
        cv2.THRESH_BINARY_INV,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    binary = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    page_area = image.shape[0] * image.shape[1]
    diagrams = []

    for idx, contour in enumerate(contours):
        x, y, w, h = cv2.boundingRect(contour)

        area = w * h
        aspect = w / float(h)
        density = cv2.countNonZero(binary[y:y + h, x:x + w]) / area

        if area < 20000:
            continue

        if area > page_area * 0.65:
            continue

        if aspect > 7.0:
            continue

        if h < 60:
            continue

        if density > 0.70:
            continue

        # Filter out blocks that are primarily text
        orig_x0, orig_y0 = x / zoom, y / zoom
        orig_x1, orig_y1 = (x + w) / zoom, (y + h) / zoom
        orig_area = (orig_x1 - orig_x0) * (orig_y1 - orig_y0)
        
        text_blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        text_overlap = 0
        for b in text_blocks:
            bx0, by0, bx1, by1 = b[:4]
            ix0 = max(orig_x0, bx0)
            iy0 = max(orig_y0, by0)
            ix1 = min(orig_x1, bx1)
            iy1 = min(orig_y1, by1)
            if ix1 > ix0 and iy1 > iy0:
                text_overlap += (ix1 - ix0) * (iy1 - iy0)
                
        if orig_area > 0 and (text_overlap / orig_area) > 0.45:
            continue

        crop = image[y:y + h, x:x + w]

        filename = os.path.join(
            temp_dir,
            f"page_{page_number}_diagram_{idx}.png",
        )

        cv2.imwrite(filename, cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))

        diagrams.append({
            "page": page_number,
            "image_path": filename,
            "bbox": [
                x / zoom,
                y / zoom,
                (x + w) / zoom,
                (y + h) / zoom,
            ],
        })

    diagrams.sort(key=lambda d: d["bbox"][1])
    return diagrams

# =========================
# IMAGE + QUESTION ALIGNMENT
# =========================

def attach_diagrams_to_questions(questions, diagrams):
    for diagram in diagrams:
        page_questions = [
            q for q in questions
            if q["page"] == diagram["page"]
        ]

        if not page_questions:
            continue

        diagram_top = diagram["bbox"][1]

        previous_questions = [
            q for q in page_questions
            if q["_bbox"][1] <= diagram_top
        ]

        if previous_questions:
            matched_question = max(
                previous_questions,
                key=lambda q: q["_bbox"][1],
            )
        else:
            matched_question = min(
                page_questions,
                key=lambda q: abs(q["_bbox"][1] - diagram_top),
            )

        try:
            image_url = upload_to_cloudinary(diagram["image_path"])
            matched_question["image_urls"].append(image_url)
        except Exception as e:
            print(f"Cloudinary upload failed: {diagram['image_path']} -> {e}")

    return questions

# =========================
# FINAL JSON CLEANUP
# =========================

def clean_final_questions(questions):
    final = []

    for q in questions:
        question_text = clean_text(q["question"])

        if not question_text:
            continue

        # we do not include _bbox
        final.append({
            "page": q["page"],
            "question_no": q["question_no"],
            "sub_question": q["sub_question"],
            "question_key": q["question_key"],
            "question": question_text,
            "marks": q["marks"],
            "has_or_before": q["has_or_before"],
            "image_urls": q["image_urls"],
        })

    return final

# =========================
# MAIN PIPELINE
# =========================

def process_pdf_file(pdf_bytes: bytes, filename: str) -> dict:
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Open PDF from bytes
    doc = fitz.open("pdf", pdf_bytes)

    all_lines = []
    all_diagrams = []
    page_width = doc.load_page(0).rect.width if len(doc) > 0 else 600

    extracted_year = None
    extracted_exam_type = None

    if len(doc) > 0:
        first_page_text = doc.load_page(0).get_text("text")
        
        # Match pattern like GUG/S/24 or GUG/W/23
        # S = Summer, W = Winter
        match = re.search(r"GUG/([SW])/(\d{2})", first_page_text, re.IGNORECASE)
        if match:
            season = match.group(1).upper()
            year_suffix = match.group(2)
            extracted_exam_type = "Summer" if season == "S" else "Winter"
            extracted_year = 2000 + int(year_suffix)

    for page_index in range(len(doc)):
        page_number = page_index + 1
        page = doc.load_page(page_index)

        page_diagrams = extract_diagrams_from_page(page, page_number, TEMP_DIR)
        all_diagrams.extend(page_diagrams)

        page_lines = get_page_lines(page, page_diagrams)
        for line in page_lines:
            line["page"] = page_number
        all_lines.extend(page_lines)

    all_questions = extract_questions_from_lines(all_lines, page_width)
    
    # ── FIX BROKEN MATH SYMBOLS USING GEMINI VISION ──
    page_to_questions = {}
    for q in all_questions:
        page_to_questions.setdefault(q["page"], []).append(q)
        
    for page_num, page_qs in page_to_questions.items():
        try:
            page = doc.load_page(page_num - 1)
            # High res for math OCR
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            
            prompt = (
                "Here is an image of a question paper page. "
                "The text below was extracted previously but the mathematical symbols, plus signs (+), minus signs, prime marks ('), "
                "and logic expressions are corrupted (often showing as weird boxes like ⭘ or missing completely).\n\n"
                "Please fix the 'question' text for EACH of these items by looking at the image. "
                "Preserve all mathematical formulas perfectly using standard text or LaTeX. "
                "CRITICAL: If a question contains a table or tabular data, you MUST format it as a proper Markdown table. DO NOT summarize or compress tables into single lines.\n"
                "CRITICAL: DO NOT generate any markdown image tags (![image](...)), <img> tags, or placeholder URLs (like imgur.com) for diagrams. We handle diagrams separately, so ONLY extract the text and tables.\n"
                "Return the result strictly as a JSON array of objects, with keys 'question_key' and 'fixed_question'.\n\n"
                "Broken questions:\n"
            )
            for q in page_qs:
                prompt += f"- [Key: {q['question_key']}] {q['question']}\n"
                
            response_text = fix_pdf_math_with_vision(img_bytes, prompt)
            clean_json = response_text.replace('```json', '').replace('```', '').strip()
            fixed_data = json.loads(clean_json)
            
            fixed_map = {str(item.get('question_key', '')): str(item.get('fixed_question', '')) for item in fixed_data}
            for q in page_qs:
                qk = str(q['question_key'])
                if qk in fixed_map and fixed_map[qk]:
                    q['question'] = fixed_map[qk]
                    
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to fix math on page {page_num}: {e}")

    attach_diagrams_to_questions(all_questions, all_diagrams)

    final_questions = clean_final_questions(all_questions)

    final_output = {
        "paper": {
            "source_pdf": filename,
            "total_pages": len(doc),
            "total_questions": len(final_questions),
            "total_diagrams": len(all_diagrams),
            "year": extracted_year,
            "exam_type": extracted_exam_type
        },
        "questions": final_questions,
    }
    
    return final_output
