import os
import ssl
import json
import time
import requests
import urllib.request
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
RENDER_WEBHOOK_URL = "https://bacend-climbup.onrender.com/api/whatsapp/webhook"
# RENDER_WEBHOOK_URL = "http://localhost:8000/api/whatsapp/webhook"

USER_PHONE = "919421393609" # Amir's WhatsApp Number
USER_ID = "1802844c-0f71-485e-8326-82a5a231e817" # Amir's Supabase User ID

def setup_ssl():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def insert_dummy_uncategorized_files(count=2):
    print(f"🚀 Inserting {count} dummy uncategorized files into Supabase...")
    ctx = setup_ssl()
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    
    files = []
    for i in range(count):
        data = json.dumps({
            "user_id": USER_ID,
            "file_url": f"https://dummy.drive.link/file_{i}",
            "title": f"test_notes_{i}.pdf",
            "type": "personal_document",
            "status": "pending",
            "sender_name": "WhatsApp Bot",
            "subject_id": None # VERY IMPORTANT: Uncategorized
        }).encode()
        
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/student_resources", data=data, headers=headers, method='POST')
        resp = urllib.request.urlopen(req, context=ctx)
        result = json.loads(resp.read().decode())
        if isinstance(result, list):
            files.append(result[0])
        else:
            files.append(result)
            
    print(f"✅ Inserted {len(files)} files successfully.")
    return files

def send_whatsapp_reply(text_message):
    print(f"\n📲 Simulating WhatsApp Text Message from {USER_PHONE}: '{text_message}'")
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test_entry_id",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "1234567890",
                                "phone_number_id": "test_phone_id"
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Amir"},
                                    "wa_id": USER_PHONE
                                }
                            ],
                            "messages": [
                                {
                                    "from": USER_PHONE,
                                    "id": "test_msg_id_" + str(int(time.time())),
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {
                                        "body": text_message
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    print(f"🌐 Sending POST request to {RENDER_WEBHOOK_URL}...")
    try:
        response = requests.post(RENDER_WEBHOOK_URL, json=payload, verify=False)
        print(f"✅ Webhook Response: {response.status_code}")
        print(f"   Body: {response.text}")
    except Exception as e:
        print(f"❌ Error hitting webhook: {e}")

if __name__ == "__main__":
    print("========================================")
    print("🧪 AUTOMATED WHATSAPP BULK CATEGORIZATION TEST")
    print("========================================\n")
    
    # 1. Insert Uncategorized Files (simulates user uploading files without caption)
    inserted_files = insert_dummy_uncategorized_files(count=2)
    
    # 2. Wait a moment to ensure DB sync
    time.sleep(2)
    
    # 3. Send WhatsApp reply indicating the subject
    # This should trigger the new "bulk update" logic in whatsapp.py
    # and send a real message to Amir's phone!
    send_whatsapp_reply("Cloud computing ke notes hain")
    
    print("\n🎉 Test completed! Check your WhatsApp phone for the Bot's reply!")
    print("Check Supabase to verify the files now have a subject_id assigned.")
