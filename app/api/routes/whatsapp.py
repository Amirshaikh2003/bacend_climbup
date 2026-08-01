from fastapi import APIRouter, HTTPException, Depends, Request
import random
import string
import os
import base64
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.services.supabase_service import _session, SUPABASE_URL, SUPABASE_KEY
from app.services.google_drive_service import upload_pdf_to_user_drive
from app.api.routes.auth import verify_token

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Integration"])

class GenerateLinkRequest(BaseModel):
    provider_refresh_token: str

class WebhookPayload(BaseModel):
    message: str
    sender_number: str
    has_media: bool
    base64_media: str = None
    mime_type: str = None
    filename: str = None

import jwt

@router.post("/generate-link")
async def generate_link_code(payload: GenerateLinkRequest, token: str = Depends(verify_token)):
    """Generates a 6-digit code for linking WhatsApp"""
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        user_id = decoded.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token format")
        
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token (no sub)")

    code = "#CLIMB" + "".join(random.choices(string.digits, k=4))
    expires_at = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    
    # Store link code along with user_id and refresh token temporarily
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    data = {
        "code": code,
        "user_id": user_id,
        "expires_at": expires_at,
        "refresh_token": payload.provider_refresh_token
    }
    
    resp = _session.post(f"{SUPABASE_URL}/rest/v1/whatsapp_links", json=data, headers=headers)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail="Failed to save link code")

    return {
        "success": True, 
        "code": code, 
        "bot_number": os.getenv("WHATSAPP_BOT_NUMBER", "+919999999999"),
    }

@router.post("/webhook")
async def whatsapp_webhook(payload: WebhookPayload):
    """Webhook for Node.js WhatsApp Bot to forward messages"""
    message = payload.message.strip()
    sender = payload.sender_number
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    
    # 1. Handle Link Code
    if message.startswith("#CLIMB"):
        # Look up link code
        resp = _session.get(f"{SUPABASE_URL}/rest/v1/whatsapp_links?code=eq.{message}", headers=headers)
        if resp.status_code == 200 and len(resp.json()) > 0:
            link_data = resp.json()[0]
            # Save to users table
            update_data = {
                "whatsapp_number": sender,
                "google_refresh_token": link_data.get("refresh_token")
            }
            update_resp = _session.patch(
                f"{SUPABASE_URL}/rest/v1/users?id=eq.{link_data['user_id']}", 
                json=update_data, 
                headers=headers
            )
            if update_resp.status_code in (200, 204):
                return {"reply": "✅ Your WhatsApp number has been successfully linked to ClimbUP! You can now send PDFs here."}
        
        return {"reply": "❌ Invalid or expired link code. Please generate a new one from your ClimbUP Profile."}
    
    # 2. Handle PDF Upload
    if payload.has_media and payload.mime_type == 'application/pdf':
        # Find user by whatsapp_number
        resp = _session.get(f"{SUPABASE_URL}/rest/v1/users?whatsapp_number=eq.{sender}", headers=headers)
        if resp.status_code == 200 and len(resp.json()) > 0:
            user = resp.json()[0]
            refresh_token = user.get("google_refresh_token")
            
            if not refresh_token:
                return {"reply": "❌ Error: Google Drive access missing. Please re-link your WhatsApp from Profile."}

            try:
                # Upload to Google Drive using the user's refresh token
                file_bytes = base64.b64decode(payload.base64_media)
                public_url = upload_pdf_to_user_drive(refresh_token, file_bytes, payload.filename)
                
                # Here you would optionally insert into `student_resources` in Supabase
                # resource_data = {"user_id": user["id"], "file_url": public_url, "title": payload.filename}
                # _session.post(f"{SUPABASE_URL}/rest/v1/student_resources", json=resource_data, headers=headers)

                return {"reply": f"📄 PDF successfully uploaded to your personal ClimbUP Drive Folder!\n🔗 Link: {public_url}"}
            except Exception as e:
                return {"reply": f"❌ Failed to upload PDF: {str(e)}"}
        
        return {"reply": "❌ Your number is not linked. Please link it from your ClimbUP Profile first."}
    
    return {"reply": "Welcome to ClimbUP WhatsApp Bot. Send a PDF to upload it, or send your #CLIMB code to link your account."}

