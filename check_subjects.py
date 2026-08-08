import os, ssl, json, urllib.request
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def db_get(path):
    req = urllib.request.Request(SUPABASE_URL + path, headers=headers)
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

# User details
university_id = "3326a6d5-5206-4a43-a9fc-705b01ad2db0"
branch_id = "96bcfb2f-4da4-4705-b546-3a151d901b81"
semester = 7

print(f"=== Subjects for Semester {semester} ===")
path = f"/rest/v1/subjects?semester=eq.{semester}&branch_id=eq.{branch_id}&university_id=eq.{university_id}"
subjects = db_get(path)
if isinstance(subjects, list):
    print(f"Found {len(subjects)} subjects:")
    for s in subjects:
        code = s.get("subject_code", "N/A")
        name = s.get("subject_name", "Unknown")
        print(f"  [{code}] {name}")
else:
    print("Error:", subjects)
    # Try without university filter
    print("\nTrying without university_id filter...")
    path2 = f"/rest/v1/subjects?semester=eq.{semester}&branch_id=eq.{branch_id}"
    subjects2 = db_get(path2)
    if isinstance(subjects2, list):
        print(f"Found {len(subjects2)} subjects:")
        for s in subjects2:
            print(f"  [{s.get('subject_code')}] {s.get('subject_name')}")
