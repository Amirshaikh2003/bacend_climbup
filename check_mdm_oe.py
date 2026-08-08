import os
import requests
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings()

load_dotenv(".env")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

print("--- Testing OE Query ---")
resp_oe = requests.get(f"{url}/rest/v1/open_elective_baskets?select=oe_id,subjects(subject_id,subject_name,subject_code)&limit=5", headers=h, verify=False)
print("OE Response:", resp_oe.status_code, resp_oe.text)

print("\n--- Testing MDM Query ---")
resp_mdm = requests.get(f"{url}/rest/v1/mdm_branch_subject_mapping?select=branch_id,semester,mdm_subjects(mdm_subject_id,subject_name,subject_code)&limit=5", headers=h, verify=False)
print("MDM Response:", resp_mdm.status_code, resp_mdm.text)
