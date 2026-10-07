import re

with open("app/api/routes/whatsapp.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace text intent parsing with Groq
code = code.replace(
    'response_text = chat_completion([{"role": "user", "content": prompt}], max_tokens=180, temperature=0.6)',
    'from app.services.ai.groq_client import chat_completion as groq_chat\n                response_text = groq_chat([{"role": "user", "content": prompt}], max_tokens=180, temperature=0.6)'
)

# Replace text PDF categorizing with Groq
code = code.replace(
    'response_text = chat_completion([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.6)',
    'from app.services.ai.groq_client import chat_completion as groq_chat\n            response_text = groq_chat([{"role": "user", "content": prompt}], max_tokens=200, temperature=0.6)'
)

with open("app/api/routes/whatsapp.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched intent parsing to use Groq")
