import requests
import time
import sys

RENDER_WEBHOOK_URL = "https://bacend-climbup.onrender.com/api/whatsapp/webhook"
USER_PHONE = "919421393609" # Amir's WhatsApp Number

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
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = "Hi, this is a test from the script!"
        
    send_whatsapp_reply(message)
