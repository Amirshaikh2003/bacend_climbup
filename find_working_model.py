import urllib.request
import json
import os
import ssl
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("No GEMINI_API_KEY")
    exit(1)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

models_to_test = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite-001",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]

print("Testing Models for Free Tier Limits...\n")

for model in models_to_test:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": "Hello"}]}]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            print(f"[SUCCESS] {model} is WORKING! Response: {data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')[:20]}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            print(f"[429 RATE LIMIT] {model} -> {body}")
        elif exc.code == 404:
            print(f"[404 NOT FOUND] {model}")
        else:
            print(f"[ERROR {exc.code}] {model} -> {body}")
    except Exception as e:
        print(f"[EXCEPTION] {model} -> {e}")
