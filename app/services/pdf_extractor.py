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

MAIN_SUB_RE = re.compile(r"^\s*(?:Q\.?)?\s*(\d{1,2})[\.\)]\s*(?:([a-d])\))?\s*(.*)", re.I)
SUB_RE = re.compile(r"^\s*(?:Q\.?)?\s*([a-d])\)\s*(.*)", re.I)
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

def clean_text(text: str) -> str:
    text = text.replace("Ω", "Ω")
    
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

def is_bad_line(text: str) -> bool:
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
        return True

    if re.fullmatch(r"\d+", text):
        return True

    # Strip leading question number just for bad line check so patterns can match
    text_no_num = re.sub(r"^(?:Q\.?)?\s*\d{1,2}[\.\)]\s*(?:[a-d]\))?\s*", "", text, flags=re.I)

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

def get_page_lines(page):
    words = page.get_text("words")
    page_w = page.rect.width
    page_h = page.rect.height

    rows = {}

    for word in words:
        x0, y0, x1, y1, text, *_ = word

        # Header/footer ignore
        if y0 < 55 or y0 > page_h - 35:
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
            if x0 > page_w * 0.86 and text.isdigit():
                mark = int(text)
                continue

            text_words.append(text)

        text = clean_text(" ".join(text_words))

        if is_bad_line(text):
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
            # Diagram labels usually appear away from main question text.
            if bbox[0] <= page_width * 0.34:
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

    for page_index in range(len(doc)):
        page_number = page_index + 1
        page = doc.load_page(page_index)

        page_lines = get_page_lines(page)
        for line in page_lines:
            line["page"] = page_number
        all_lines.extend(page_lines)

        page_diagrams = extract_diagrams_from_page(page, page_number, TEMP_DIR)
        all_diagrams.extend(page_diagrams)

    all_questions = extract_questions_from_lines(all_lines, page_width)
    attach_diagrams_to_questions(all_questions, all_diagrams)

    final_questions = clean_final_questions(all_questions)

    final_output = {
        "paper": {
            "source_pdf": filename,
            "total_pages": len(doc),
            "total_questions": len(final_questions),
            "total_diagrams": len(all_diagrams),
        },
        "questions": final_questions,
    }
    
    return final_output
