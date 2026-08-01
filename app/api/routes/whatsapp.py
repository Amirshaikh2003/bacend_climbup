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
import json
from app.services.ai.gemini_client import chat_completion

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

def _categorize_pdf(caption: str, subjects: list) -> dict:
    if not caption:
        return {"type": "Notes", "subject_id": None, "reply_message": "📄 PDF uploaded to your Drive!\n\n*(Tip: To categorize this file, just reply to me right now with the subject name, e.g. 'Cloud Computing Assignment')*\n\n🔗 Link: {link}"}
    
    subjects_str = json.dumps([{"id": s.get("subject_id"), "name": s.get("subject_name", ""), "code": s.get("subject_code", "")} for s in subjects if s.get("subject_id")])
    
    prompt = f"""You are an AI assistant for the ClimbUP student platform. A student uploaded a PDF with the following caption: "{caption}"
Available Subjects: {subjects_str}

Tasks:
1. Determine if this is an "Assignment", "Practical", "Question Paper", or "Notes". Default to "Notes".
2. Match the caption to the closest Subject from the Available Subjects. If no match is found, return null for subject_id.
3. Write a highly positive, encouraging, and short reply message (1-2 sentences) confirming the upload and the categorization. Mention the subject name if matched. Include exactly this placeholder for the drive link: "\n🔗 Link: {{link}}". Do not include emojis in the placeholder itself.

Return ONLY a valid JSON object matching this schema exactly:
{{
    "type": "string",
    "subject_id": "uuid string or null",
    "reply_message": "string"
}}"""
    try:
        response_text = chat_completion([{"role": "user", "content": prompt}], max_tokens=300, temperature=0.1)
        if response_text.startswith("```json"):
            response_text = response_text[7:-3]
        elif response_text.startswith("```"):
            response_text = response_text[3:-3]
            
        data = json.loads(response_text.strip())
        return {
            "type": data.get("type", "Notes"),
            "subject_id": data.get("subject_id"),
            "reply_message": data.get("reply_message", "📄 PDF successfully uploaded and categorized!\n🔗 Link: {link}")
        }
    except Exception as e:
        print("Gemini Categorization Error:", e)
        return {"type": "Notes", "subject_id": None, "reply_message": "📄 PDF successfully uploaded to your Drive! (AI categorization failed)\n🔗 Link: {link}"}

def _chat_with_student(message: str, sender: str, headers: dict) -> str:
    if not message:
        return "Welcome to ClimbUP WhatsApp Bot. Send a PDF to upload it, or send your #CLIMB code to link your account."

    # 1. Lookup user
    user_resp = _session.get(f"{SUPABASE_URL}/rest/v1/users?whatsapp_number=eq.{sender}", headers=headers)
    if user_resp.status_code == 200 and len(user_resp.json()) > 0:
        user_id = user_resp.json()[0]["id"]
        
        # 2. Find their most recent resource
        res_resp = _session.get(f"{SUPABASE_URL}/rest/v1/student_resources?user_id=eq.{user_id}&order=created_at.desc&limit=1", headers=headers)
        if res_resp.status_code == 200 and len(res_resp.json()) > 0:
            last_resource = res_resp.json()[0]
            resource_id = last_resource["id"]
            
            # Fetch subjects for matching
            subjects = []
            subj_resp = _session.get(f"{SUPABASE_URL}/rest/v1/subjects", headers=headers)
            if subj_resp.status_code == 200:
                subjects = subj_resp.json()
                
            subjects_str = json.dumps([{"id": s.get("subject_id"), "name": s.get("subject_name", ""), "code": s.get("subject_code", "")} for s in subjects if s.get("subject_id")])

            prompt = f"""You are the ClimbUP WhatsApp assistant. 
A student sent this text message: "{message}"
They recently uploaded a PDF named: "{last_resource.get('title', 'Unknown')}".
Available Subjects: {subjects_str}

Is the student trying to provide a subject or category (like Assignment, Practical, Notes) for their recently uploaded PDF?
If YES:
1. Determine if it's "Assignment", "Practical", "Question Paper", or "Notes". Default to Notes.
2. Match it to the closest Subject ID from the Available Subjects list.
3. Write a short confirmation message (e.g. "✅ Got it! I've categorized your recent PDF as an Assignment for Cloud Computing.")
Return EXACTLY this JSON format (no markdown code blocks): {{"is_categorization": true, "type": "...", "subject_id": "...", "reply_message": "..."}}

If NO (they are just saying hi, or asking a general question):
Write a helpful, friendly reply. Return EXACTLY this JSON format: {{"is_categorization": false, "reply_message": "..."}}"""

            try:
                response_text = chat_completion([{"role": "user", "content": prompt}], max_tokens=300, temperature=0.1)
                if response_text.startswith("```json"):
                    response_text = response_text[7:-3]
                elif response_text.startswith("```"):
                    response_text = response_text[3:-3]
                    
                data = json.loads(response_text.strip())
                
                if data.get("is_categorization") and data.get("subject_id"):
                    # Update the resource!
                    update_payload = {"type": data.get("type", "Notes"), "subject_id": data.get("subject_id")}
                    _session.patch(f"{SUPABASE_URL}/rest/v1/student_resources?id=eq.{resource_id}", json=update_payload, headers=headers)
                    return data.get("reply_message", "✅ Categorized your file successfully!")
                elif data.get("reply_message"):
                    return data.get("reply_message")
            except Exception as e:
                print("Gemini Chat Categorization Error:", e)
                pass # Fall through to generic chat

    prompt = f"""You are the ClimbUP WhatsApp assistant. A student sent this message: "{message}"
Reply in a very helpful, friendly, and brief manner. If they seem lost, remind them they can send PDFs (with captions to categorize them) or a #CLIMB code to link their account."""
    try:
        return chat_completion([{"role": "user", "content": prompt}], max_tokens=150, temperature=0.4).strip()
    except:
        return "Welcome to ClimbUP WhatsApp Bot. Send a PDF to upload it, or send your #CLIMB code to link your account."

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
                
                # Fetch subjects for AI categorization
                subjects = []
                subj_resp = _session.get(f"{SUPABASE_URL}/rest/v1/subjects", headers=headers)
                if subj_resp.status_code == 200:
                    subjects = subj_resp.json()
                
                # Ask Gemini to categorize
                ai_result = _categorize_pdf(message, subjects)
                
                # Save the resource to Supabase so it shows up in their profile
                resource_data = {
                    "user_id": user["id"], 
                    "file_url": public_url, 
                    "title": payload.filename or "My Notes",
                    "type": ai_result["type"],
                    "status": "pending",
                    "sender_name": "WhatsApp Bot"
                }
                
                if ai_result["subject_id"]:
                    resource_data["subject_id"] = ai_result["subject_id"]
                
                db_resp = _session.post(f"{SUPABASE_URL}/rest/v1/student_resources", json=resource_data, headers=headers)
                if db_resp.status_code not in (200, 201):
                    print("Warning: Failed to save to Supabase student_resources table", db_resp.text)

                reply = ai_result["reply_message"].replace("{link}", public_url)
                return {"reply": reply}
            except Exception as e:
                return {"reply": f"❌ Failed to upload PDF: {str(e)}"}
        
        return {"reply": "❌ Your number is not linked. Please link it from your ClimbUP Profile first."}
    
    # 3. Handle Normal Conversational Message
    return {"reply": _chat_with_student(message, sender, headers)}

