import os
import requests
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
resp = requests.get(f"{SUPABASE_URL}/rest/v1/whatsapp_links?order=expires_at.desc&limit=5", headers=headers, verify=False)
print("Status:", resp.status_code)
print("Response:", resp.text)
