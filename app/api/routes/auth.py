import os
import smtplib
import random
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()
security = HTTPBearer()

ADMINS = {
    "Amir": "shaikhamir1003@gmail.com",
    "Saloni": "salonipatle13@gmail.com",
    "Nilesh": "kagnenilesh05@gmail.com",
    "Shweeta": "shwetameshram445@gmail.com"
}

# Temporary in-memory store for OTPs
# Structure: { email: {"otp": 123456, "expires_at": timestamp} }
OTP_STORE = {}

class SendOtpRequest(BaseModel):
    admin_name: str

class VerifyOtpRequest(BaseModel):
    admin_name: str
    otp: str

def send_email_otp(to_email: str, admin_name: str, otp: str):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USERNAME")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    
    if not all([smtp_host, smtp_user, smtp_pass]):
        raise ValueError("SMTP configuration is missing in environment variables.")

    sender_email = "transporteyesystem@gmail.com"
    
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = "Climbup Admin Login OTP"
    
    body = f"Hello {admin_name},\n\nYour OTP for logging into the Climbup Admin panel is: {otp}\n\nThis OTP will expire in 5 minutes.\n\nThanks,\nClimbup Team"
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to send email to {to_email}: {e}")
        raise ValueError("Failed to send OTP email.")

@router.post("/send-otp")
async def send_otp(request: SendOtpRequest):
    admin_name = request.admin_name
    if admin_name not in ADMINS:
        raise HTTPException(status_code=400, detail="Invalid Admin Name selected.")
    
    email = ADMINS[admin_name]
    
    # Generate 6 digit OTP
    otp = str(random.randint(100000, 999999))
    
    # Store OTP with 5 minute expiration
    expires_at = time.time() + 300
    OTP_STORE[email] = {"otp": otp, "expires_at": expires_at}
    
    try:
        send_email_otp(email, admin_name, otp)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"success": True, "message": f"OTP sent successfully to {admin_name}'s email."}

@router.post("/verify-otp")
async def verify_otp(request: VerifyOtpRequest):
    admin_name = request.admin_name
    if admin_name not in ADMINS:
        raise HTTPException(status_code=400, detail="Invalid Admin Name selected.")
        
    email = ADMINS[admin_name]
    stored_data = OTP_STORE.get(email)
    
    if not stored_data:
        raise HTTPException(status_code=400, detail="No OTP requested or OTP expired.")
        
    if time.time() > stored_data["expires_at"]:
        del OTP_STORE[email]
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")
        
    if stored_data["otp"] != request.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP entered.")
        
    # Clear OTP after successful verification
    del OTP_STORE[email]
    
    # Return a simple mock token or success flag
    return {"success": True, "token": f"admin_token_{admin_name.lower()}", "admin_name": admin_name}

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    # 1. Check if it's an admin token
    valid_admin_tokens = [f"admin_token_{name.lower()}" for name in ADMINS.keys()]
    if token in valid_admin_tokens:
        return token
        
    # 2. Check if it's a valid Supabase User JWT
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    
    if supabase_url and supabase_key:
        import urllib.request
        import urllib.error
        import json
        import asyncio
        
        url = f"{supabase_url}/auth/v1/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": supabase_key
        }
        
        req = urllib.request.Request(url, headers=headers)
        try:
            def fetch_user():
                with urllib.request.urlopen(req, timeout=5) as response:
                    return json.loads(response.read().decode())
            
            await asyncio.to_thread(fetch_user)
            return token  # Valid Supabase user token
        except Exception:
            pass  # Fall through to 401

    raise HTTPException(status_code=401, detail="Invalid or expired token")
