import re

with open("app/api/routes/whatsapp.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add import
if "process_and_embed_document" not in code:
    code = code.replace("from app.services.ai.gemini_client import chat_completion, categorize_pdf_with_vision", 
                        "from app.services.ai.gemini_client import chat_completion, categorize_pdf_with_vision\nfrom app.services.ai.rag_service import process_and_embed_document\nimport threading")

# 2. Add RAG trigger for delayed categorizations
target1 = """                                    public_url = upload_file_to_user_drive(None, file_resp.content, file_title, mime_type)
                                    if public_url:
                                        update_payload["file_url"] = public_url
                                    else:
                                        return f"❌ System Error: Failed to upload file to Google Drive." """

replacement1 = """                                    public_url = upload_file_to_user_drive(None, file_resp.content, file_title, mime_type)
                                    if public_url:
                                        update_payload["file_url"] = public_url
                                        # Trigger RAG Ingestion in background
                                        threading.Thread(target=process_and_embed_document, args=(user.get("user_id") or user.get("id"), final_subject_id, file_title, file_resp.content, mime_type), daemon=True).start()
                                    else:
                                        return f"❌ System Error: Failed to upload file to Google Drive." """

# Because powershell/python charset might mess up the emojis, let's use regex matching
import re
code = re.sub(
    r'(public_url = upload_file_to_user_drive\([^)]+\)\s+if public_url:\s+update_payload\["file_url"\] = public_url)',
    r'\1\n                                        threading.Thread(target=process_and_embed_document, args=(user.get("user_id") or user.get("id"), final_subject_id, file_title, file_resp.content, mime_type), daemon=True).start()',
    code
)

code = re.sub(
    r'(public_url = upload_file_to_user_drive\(None, file_bytes, filename, mime_type\)\s+status = "pending".*?)',
    r'\1\n                                threading.Thread(target=process_and_embed_document, args=(user.get("user_id") or user.get("id"), final_subject_id, filename, file_bytes, mime_type), daemon=True).start()',
    code
)


with open("app/api/routes/whatsapp.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched whatsapp.py")
