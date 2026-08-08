import os
import time
import requests
import json
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
WHATSAPP_PHONE_ID = os.getenv('WHATSAPP_PHONE_ID')
RENDER_WEBHOOK_URL = "https://bacend-climbup.onrender.com/api/whatsapp/webhook"

USER_PHONE = "919421393609" # Amir's WhatsApp Number

def upload_pdf_to_meta():
    print("1\ufe0f\u20e3 Uploading a real PDF to Meta's servers to get a valid media_id...")
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/media"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}"
    }
    
    # Create a tiny dummy PDF in memory
    dummy_pdf_bytes = (
        b"%PDF-1.4\n1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
        b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
        b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>>\nendobj\n"
        b"xref\n0 4\ntrailer\n<</Size 4 /Root 1 0 R>>\nstartxref\n200\n%%EOF"
    )
    
    files = {
        'file': ('dummy_test.pdf', dummy_pdf_bytes, 'application/pdf')
    }
    data = {
        'messaging_product': 'whatsapp'
    }
    
    response = requests.post(url, headers=headers, files=files, data=data)
    if response.status_code == 200:
        media_id = response.json().get('id')
        print(f"   \u2705 Success! Meta gave us media_id: {media_id}")
        return media_id
    else:
        print(f"   \u274c Failed to upload to Meta: {response.text}")
        return None

def simulate_webhook(payload_type, media_id=None, text=None):
    if payload_type == "document":
        print(f"2\ufe0f\u20e3 Simulating user sending the PDF via WhatsApp Webhook...")
        message_data = {
            "from": USER_PHONE,
            "id": "test_msg_id_" + str(int(time.time())),
            "timestamp": str(int(time.time())),
            "type": "document",
            "document": {
                "mime_type": "application/pdf",
                "sha256": "fake_hash",
                "id": media_id,
                "filename": "real_test_notes.pdf"
            }
        }
    else:
        print(f"4\ufe0f\u20e3 Simulating user sending subject text: '{text}'...")
        message_data = {
            "from": USER_PHONE,
            "id": "test_msg_id_" + str(int(time.time())),
            "timestamp": str(int(time.time())),
            "type": "text",
            "text": {
                "body": text
            }
        }

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "test_entry_id",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "1234567890",
                        "phone_number_id": WHATSAPP_PHONE_ID
                    },
                    "contacts": [{"profile": {"name": "Amir"}, "wa_id": USER_PHONE}],
                    "messages": [message_data]
                },
                "field": "messages"
            }]
        }]
    }

    try:
        response = requests.post(RENDER_WEBHOOK_URL, json=payload, verify=False)
        print(f"   \u2705 Webhook Response: {response.status_code}")
    except Exception as e:
        print(f"   \u274c Error hitting webhook: {e}")

if __name__ == "__main__":
    print("\n========================================================")
    print("🧪 100% REAL END-TO-END WHATSAPP TEST (WITHOUT DB CHEATS)")
    print("========================================================\n")
    
    # Step 1: Get a real media ID from Meta
    real_media_id = upload_pdf_to_meta()
    
    if real_media_id:
        # Step 2: Send Webhook to Render (Simulate PDF upload)
        # Render will download from Meta -> Upload to Google Drive -> Save to Supabase
        simulate_webhook("document", media_id=real_media_id)
        
        # Step 3: Wait like a real user
        print("\n3\ufe0f\u20e3 Waiting for 8 seconds (Simulating user reading the bot's reply)...\n")
        time.sleep(8)
        
        # Step 4: Send text message to categorize
        simulate_webhook("text", text="Cloud computing")
        
        print("\n\ud83c\udf89 100% REAL PIPELINE TEST COMPLETED!")
        print("Check your phone. You should have received two messages:")
        print("1. 'File securely save ho gayi...'")
        print("2. 'Done Amir! Aapki pending file(s) categorize ho gayi...'")
