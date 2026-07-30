import os
import re
import json
import uuid
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
    if "time :" in text_lower or "time:" in text_lower or "max. marks" in text_lower or "max marks" in text_lower:
        return True
    if text_lower.startswith("notes :") or text_lower.startswith("note :") or text_lower.startswith("notes:"):
        return True
        
    # If a line has a right-side mark, it is almost certainly a legitimate question (or part of one)
    if has_mark:
        return False
        
    # Strip leading question number just for bad line check so patterns can match
    text_no_num = re.sub(r"^(?:Q\s*\.?)?\s*\d{1,2}\s*[\.\)]\s*(?:[a-hj-uw-yz]\s*\))?\s*", "", text, flags=re.I).strip()
    text_no_num_lower = text_no_num.lower()
    
    note_phrases = [
        "all questions carry",
        "illustrate your answers",
        "all questions are compulsory",
        "due credit will be given",
        "assume suitable data",
        "use of slide rule",
        "non programmable",
        "thermodynamic tables for moist air",
        "diagrams and chemical equation",
    ]
    for phrase in note_phrases:
        if text_no_num_lower.startswith(phrase):
            return True
        if phrase in text_no_num_lower:
            # Standalone notes are usually short sentences. 
            # If the line is long and doesn't start with the phrase, it's likely a question.
            if len(text) < 75:
                return True
                
    if "wherever necessary" in text_no_num_lower and len(text) < 75:
        return True

    text = clean_text(text)

    if not text:
        return not has_mark

    if re.fullmatch(r"\d+", text):
        return True

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

        # Ignore words that are deep inside any diagram
        inside_diagram = False
        for diagram in page_diagrams:
            dx0, dy0, dx1, dy1 = diagram["bbox"]
            # Check if the center of the word falls inside the diagram
            # We add a 12-point safe margin to top/bottom so we don't accidentally drop 
            # the question text if the diagram bounding box is slightly too large.
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            if dx0 <= cx <= dx1 and (dy0 + 12) <= cy <= (dy1 - 12):
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
            new_main = main_match.group(1)
            
            # Check if this is a sub-sub-question (like '1)', '2)') disguised as a main question
            is_sub_sub = False
            if current_main and new_main.isdigit() and current_main.isdigit():
                if int(new_main) <= int(current_main):
                    # Sub-sub questions typically use parentheses
                    after_num = text.split(new_main, 1)[-1]
                    if ")" in after_num[:3]:
                        # Check indentation relative to the current question
                        if current and bbox[0] > current["_bbox"][0] + 10:
                            is_sub_sub = True
                            
            if is_sub_sub and current:
                current["question"] += "\n" + text
                current["_bbox"][2] = max(current["_bbox"][2], bbox[2])
                current["_bbox"][3] = bbox[3]
                continue

            save_current()

            current_main = new_main
            sub = (main_match.group(2) or "").lower()
            q_text = clean_text(main_match.group(3))

            current = {
                "page": page_number,
                "question_no": current_main,
                "sub_question": sub,
                "question_key": f"{current_main}{sub}_{uuid.uuid4().hex[:6]}",
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
                "question_key": f"{current_main}{sub}_{uuid.uuid4().hex[:6]}",
                "question": q_text,
                "marks": mark,
                "has_or_before": False, # 'or' before a sub-question isn't usually a thing
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

    # Use a wider kernel to merge horizontally but less vertically 
    # to prevent swallowing the question text paragraphs above diagrams.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 7))
    binary = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    page_area = image.shape[0] * image.shape[1]
    diagrams = []

    text_words = page.get_text("words")
    valid_bboxes = []

    # Pass 1: Filter out text blocks and tiny noise
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        orig_x0, orig_y0 = x / zoom, y / zoom
        orig_x1, orig_y1 = (x + w) / zoom, (y + h) / zoom
        orig_area = (orig_x1 - orig_x0) * (orig_y1 - orig_y0)
        
        text_overlap = 0
        for w_box in text_words:
            bx0, by0, bx1, by1 = w_box[:4]
            ix0 = max(orig_x0, bx0)
            iy0 = max(orig_y0, by0)
            ix1 = min(orig_x1, bx1)
            iy1 = min(orig_y1, by1)
            if ix1 > ix0 and iy1 > iy0:
                text_overlap += (ix1 - ix0) * (iy1 - iy0)
                
        if orig_area > 0 and (text_overlap / orig_area) > 0.45:
            continue
            
        if w * h < 500:
            continue
            
        valid_bboxes.append([x, y, x + w, y + h])

    # Pass 2: Merge bounding boxes that are close to each other
    merge_thresh = 40  # pixels
    merged_bboxes = []
    while valid_bboxes:
        box = valid_bboxes.pop(0)
        x0, y0, x1, y1 = box
        
        has_merged = True
        while has_merged:
            has_merged = False
            for i in range(len(valid_bboxes) - 1, -1, -1):
                bx0, by0, bx1, by1 = valid_bboxes[i]
                
                dx = max(0, max(x0, bx0) - min(x1, bx1))
                dy = max(0, max(y0, by0) - min(y1, by1))
                
                if dx <= merge_thresh and dy <= merge_thresh:
                    x0 = min(x0, bx0)
                    y0 = min(y0, by0)
                    x1 = max(x1, bx1)
                    y1 = max(y1, by1)
                    valid_bboxes.pop(i)
                    has_merged = True
        
        merged_bboxes.append([x0, y0, x1, y1])

    diagrams = []
    for idx, bbox in enumerate(merged_bboxes):
        x, y, x1, y1 = bbox
        w = x1 - x
        h = y1 - y

        area = w * h
        aspect = w / float(h) if h > 0 else 100
        density = cv2.countNonZero(binary[y:y + h, x:x + w]) / area if area > 0 else 0

        if area < 10000:
            continue

        if area > page_area * 0.65:
            continue

        if aspect > 15.0:
            continue

        if h < 40:
            continue

        if density > 0.70:
            continue

        orig_x0, orig_y0 = x / zoom, y / zoom
        orig_x1, orig_y1 = (x + w) / zoom, (y + h) / zoom

        # Pad the visual crop to ensure we capture detached labels (like 80kN, 1.5m) 
        # without affecting the logical bounding box used for text deletion.
        pad_y = 80  # 20 points
        pad_x = 40  # 10 points
        
        crop_y = max(0, y - pad_y)
        crop_x = max(0, x - pad_x)
        crop_h = min(image.shape[0] - crop_y, h + pad_y * 2)
        crop_w = min(image.shape[1] - crop_x, w + pad_x * 2)

        crop = image[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]

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
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    all_diagrams = []
    final_questions = []

    extracted_year = None
    extracted_exam_type = None

    if len(doc) > 0:
        first_page_text = doc.load_page(0).get_text("text")
        
        # Match pattern like GUG/S/24 or GUG/W/23
        match = re.search(r"GUG/([SW])/(\d{2})", first_page_text, re.IGNORECASE)
        if match:
            season = match.group(1).upper()
            year_suffix = match.group(2)
            extracted_exam_type = "Summer" if season == "S" else "Winter"
            extracted_year = 2000 + int(year_suffix)

    for page_index in range(len(doc)):
        page_number = page_index + 1
        page = doc.load_page(page_index)
        
        # 1. Extract diagrams using OpenCV
        page_diagrams = extract_diagrams_from_page(page, page_number, TEMP_DIR)
        all_diagrams.extend(page_diagrams)
        
        # High res image for the Agent
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        
        # 2. Ask Gemini 1.5 Flash to perfectly extract all questions
        try:
            agent_response_json = extract_page_questions_agentic(img_bytes)
            clean_json = agent_response_json.replace('```json', '').replace('```', '').strip()
            page_questions = json.loads(clean_json)
        except Exception as e:
            print(f"Error during agentic extraction on page {page_number}: {e}")
            page_questions = []
            
        # 3. Map diagrams to questions based on Y-coordinates
        # We find the question whose ymin is just above the diagram's top edge
        for q in page_questions:
            q["page"] = page_number
            q["image_urls"] = []
            # Generate UUID key
            q["question_key"] = f"{q.get('question_no', '')}{q.get('sub_question', '')}_{uuid.uuid4().hex[:6]}"
            
        for diagram in page_diagrams:
            # OpenCV diagram bbox is [x0, y0, x1, y1] in raw page coordinates
            # Normalize y0 to 0-1000 scale
            page_h = page.rect.height
            normalized_diagram_top = (diagram["bbox"][1] / page_h) * 1000
            
            # Find questions that appear before this diagram (ymin < diagram_top)
            # Add a small buffer (e.g., 50 units) to allow for minor LLM misalignment
            previous_questions = [q for q in page_questions if q.get("ymin", 0) <= normalized_diagram_top + 50]
            
            if previous_questions:
                # Assign to the question closest to the diagram from above
                matched_question = max(
                    previous_questions,
                    key=lambda q: q.get("ymin", 0),
                )
                matched_question["image_urls"].append(diagram["url"])
                
        final_questions.extend(page_questions)

    # Calculate total marks
    total_marks = sum(int(q.get("marks", 0)) for q in final_questions if str(q.get("marks", "")).isdigit())

    # Final cleanup of TEMP_DIR
    for f in os.listdir(TEMP_DIR):
        try:
            os.remove(os.path.join(TEMP_DIR, f))
        except:
            pass

    return {
        "paper": {
            "source_pdf": filename,
            "total_pages": len(doc),
            "total_questions": len(final_questions),
            "total_diagrams": len(all_diagrams),
            "year": extracted_year,
            "exam_type": extracted_exam_type,
            "total_marks": total_marks
        },
        "questions": final_questions,
        "diagrams": all_diagrams
    }
