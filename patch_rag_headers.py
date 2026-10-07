with open("app/services/ai/rag_service.py", "r", encoding="utf-8") as f:
    code = f.read()

replacement = """    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }"""

code = code.replace("    headers = get_headers()", replacement)

with open("app/services/ai/rag_service.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Fixed headers in rag_service.py")
