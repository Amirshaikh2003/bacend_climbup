import urllib.request, json, ssl, time

base_url = 'https://bacend-climbup.onrender.com'
sender = '919421393609'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def send_webhook(msg):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "12345",
            "changes": [{
                "value": {
                    "messages": [{
                        "from": sender,
                        "type": "text",
                        "text": {"body": msg}
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/api/whatsapp/webhook",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
        return resp.read().decode()
    except urllib.error.HTTPError as e:
        return f"HTTP Error {e.code}: {e.read().decode()}"
    except Exception as e:
        return f"Error: {e}"

print("=" * 60)
print("CLIMBUP BOT - END TO END TEST")
print("=" * 60)

print("\n[TEST 1] Sending chat message...")
r = send_webhook("hello, what can you do for me?")
print("Server Response:", r)
print(">>> Now CHECK your WhatsApp for bot reply!")

print("\nWaiting 5 seconds before next test...")
time.sleep(5)

print("\n[TEST 2] Sending a subject categorization message...")
r = send_webhook("Physics")
print("Server Response:", r)
print(">>> Now CHECK your WhatsApp - bot should say it categorized the file in Physics!")

print("\nWaiting 5 seconds before next test...")
time.sleep(5)

print("\n[TEST 3] Sending a general question...")
r = send_webhook("Explain Newton's First Law in simple words")
print("Server Response:", r)
print(">>> Now CHECK your WhatsApp for AI explanation!")

print("\n" + "=" * 60)
print("ALL TESTS DONE! Check WhatsApp for 3 replies from bot.")
print("=" * 60)
