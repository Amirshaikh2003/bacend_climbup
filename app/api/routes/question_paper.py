from fastapi import APIRouter, File, UploadFile, HTTPException
from app.services.pdf_extractor import process_pdf
import tempfile
import os
import shutil

router = APIRouter(prefix="/question-paper", tags=["Question Paper"])

@router.post("/upload")
async def upload_question_paper(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    # Save uploaded file to a temporary file
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        # Process the PDF using our new extractor logic
        result = process_pdf(temp_path)
        
        # Add original filename instead of temp filename
        result["paper"]["source_pdf"] = file.filename
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
