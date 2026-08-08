"""
ClimbUP - Google Drive Upload Test
Tests: Real PDF file creation -> Actual Google Drive upload -> URL verification
"""
import os, sys, json, ssl, urllib.request
from dotenv import load_dotenv
load_dotenv()

def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

sep("STEP 1: Checking Google Drive credentials")

CLIENT_ID     = os.getenv("GOOGLE_ADMIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_ADMIN_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GOOGLE_ADMIN_REFRESH_TOKEN")
FOLDER_ID     = os.getenv("TARGET_FOLDER_ID")

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print("FAIL: Missing Google credentials!")
    print(f"  GOOGLE_ADMIN_CLIENT_ID     : {'OK' if CLIENT_ID else 'MISSING'}")
    print(f"  GOOGLE_ADMIN_CLIENT_SECRET : {'OK' if CLIENT_SECRET else 'MISSING'}")
    print(f"  GOOGLE_ADMIN_REFRESH_TOKEN : {'OK' if REFRESH_TOKEN else 'MISSING'}")
    sys.exit(1)
else:
    print("PASS: All Google credentials found!")
    print(f"  CLIENT_ID     : {CLIENT_ID[:20]}...")
    print(f"  REFRESH_TOKEN : {REFRESH_TOKEN[:20]}...")
    print(f"  FOLDER_ID     : {FOLDER_ID or 'Not set (will create ClimbUP folder)'}")

sep("STEP 2: Importing Google Drive service")
try:
    sys.path.insert(0, '.')
    from app.services.google_drive_service import upload_file_to_user_drive
    print("PASS: Google Drive service imported successfully!")
except ImportError as e:
    print(f"FAIL: Could not import Google Drive service: {e}")
    sys.exit(1)

sep("STEP 3: Creating test PDF file")
# Create a minimal real PDF file
test_pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 24 Tf 100 700 Td (ClimbUP Test PDF) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
300
%%EOF"""

print(f"PASS: Test PDF created ({len(test_pdf_content)} bytes)")

sep("STEP 4: Uploading to Google Drive (REAL UPLOAD)")
print("Uploading 'ClimbUP_Test_Physics_Notes.pdf' to Google Drive...")
try:
    url = upload_file_to_user_drive(
        refresh_token=None,
        file_bytes=test_pdf_content,
        filename="ClimbUP_Test_Physics_Notes.pdf",
        mime_type="application/pdf"
    )
    if url and "drive.google.com" in url:
        print(f"PASS: File uploaded to Google Drive!")
        print(f"  Public URL : {url}")
        print(f"\n  >>> Open this URL in browser to verify the PDF: {url}")
    else:
        print(f"FAIL: Upload returned invalid URL: {url}")
except PermissionError as e:
    print(f"FAIL: Permission error - {e}")
    print("  Make sure GOOGLE_ADMIN_REFRESH_TOKEN uses a personal Gmail (not GSuite/Workspace)")
except Exception as e:
    print(f"FAIL: Upload error - {type(e).__name__}: {e}")

sep("FINAL RESULT")
print("If URL above is valid, Google Drive upload is 100% working!")
print("Real PDF from WhatsApp will be stored in the same ClimbUP folder.")
