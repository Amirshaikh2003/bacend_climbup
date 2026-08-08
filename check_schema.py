import os
import requests
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings()

load_dotenv(".env")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
h = {"apikey": key, "Authorization": f"Bearer {key}"}

res = requests.get(f"{url}/rest/v1/", headers=h, verify=False).json()
schema = res.get("definitions", {}).get("student_resources", {})

for k, v in schema.get("properties", {}).items():
    print(f"{k}: {v.get('enum', '')}")
