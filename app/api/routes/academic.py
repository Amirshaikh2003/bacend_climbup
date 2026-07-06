from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import logging

from app.services.supabase_service import (
    get_universities,
    get_branches,
    get_semesters,
    get_subjects,
)

router = APIRouter(prefix="/academic", tags=["Academic Hierarchy"])
logger = logging.getLogger(__name__)

@router.get("/universities")
def list_universities():
    try:
        data = get_universities()
        return {"success": True, "universities": data}
    except Exception as e:
        logger.error(f"Error fetching universities: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch universities")

@router.get("/branches")
def list_branches(university_id: str):
    if not university_id:
        raise HTTPException(status_code=400, detail="university_id is required")
    try:
        data = get_branches(university_id)
        return {"success": True, "branches": data}
    except Exception as e:
        logger.error(f"Error fetching branches: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch branches")

@router.get("/semesters")
def list_semesters(branch_id: str):
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    try:
        data = get_semesters(branch_id)
        return {"success": True, "semesters": data}
    except Exception as e:
        logger.error(f"Error fetching semesters: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch semesters")

@router.get("/subjects")
def list_subjects(semester_id: str):
    if not semester_id:
        raise HTTPException(status_code=400, detail="semester_id is required")
    try:
        data = get_subjects(semester_id)
        return {"success": True, "subjects": data}
    except Exception as e:
        logger.error(f"Error fetching subjects: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch subjects")
