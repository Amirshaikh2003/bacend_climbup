import re

with open("app/api/routes/whatsapp.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update the Intent logic prompt in whatsapp.py
intent_search = """TASK: Determine the user's intent. Are they categorizing their recent upload?
  - Match subjects ONLY from their enrolled list above (be smart: "cloud" = Cloud Computing, "tcp" = TCP/IP).
  - If they are naming a subject for their recent upload: set intent="categorize", fill subject_id.
  - If the subject mentioned is NOT in their list: set intent="wrong_subject".
  - If it's just a general chat/greeting: set intent="chat"."""

intent_replace = """TASK: Determine the user's intent.
  - Match subjects ONLY from their enrolled list above (be smart: "cloud" = Cloud Computing, "tcp" = TCP/IP).
  - If they are naming a subject for their recent upload: set intent="categorize", fill subject_id.
  - If they are ASKING A QUESTION about their subjects (e.g. "what is newton's law", "explain OSI model", "how does a compiler work"): set intent="ask_question" and fill the BEST MATCHING subject_id. If no subject matches the topic, set subject_id to null.
  - If the subject mentioned for upload is NOT in their list: set intent="wrong_subject".
  - If it's just a general chat/greeting: set intent="chat"."""

code = code.replace(intent_search, intent_replace)

# 2. Add the RAG querying block
rag_logic = """
                elif intent == "ask_question":
                    subject_id_to_query = data.get("subject_id")
                    
                    if not subject_id_to_query:
                        return f"🤔 I'm not sure which subject you are asking about, {user_name}. Please mention the subject name (e.g., 'In physics, what is...')!"
                        
                    from app.services.ai.rag_service import search_notes
                    user_id = user.get("user_id") or user.get("id")
                    
                    # 1. Search Vector DB
                    chunks = search_notes(user_id, subject_id_to_query, text_message, top_k=3)
                    
                    if not chunks:
                        return f"📚 I looked through your notes for this subject, but couldn't find anything related to '{text_message}'. Try uploading more notes!"
                        
                    # 2. Build Context
                    context_text = "\\n\\n".join([f"From Note ({c.get('file_name', 'Unknown')}): {c.get('content', '')}" for c in chunks])
                    
                    # 3. Generate Smart RAG Answer
                    rag_prompt = f"You are ClimbUP's AI Tutor. Answer the student's question based strictly on the provided Notes Context below. Be highly accurate, concise, and professional. Do NOT mention the system or that you are reading chunks. If the answer is not in the context, say so gracefully.\\n\\nQuestion: {text_message}\\n\\nNotes Context:\\n{context_text}"
                    
                    try:
                        from app.services.ai.gemini_client import chat_completion
                        final_answer = chat_completion([{"role": "user", "content": rag_prompt}], max_tokens=1000, temperature=0.3)
                        return final_answer.strip()
                    except Exception as e:
                        print(f"RAG Generation Error: {e}")
                        return "❌ Sorry, I faced an issue reading your notes. Please try again."

"""

# Insert rag_logic before elif intent == "wrong_subject":
code = code.replace('                elif intent == "wrong_subject":', rag_logic + '                elif intent == "wrong_subject":')

with open("app/api/routes/whatsapp.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched whatsapp.py with RAG querying logic")
