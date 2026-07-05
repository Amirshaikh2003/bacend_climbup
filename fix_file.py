import sys

file_path = 'app/services/ai/question_analyzer.py'
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # The exact string in the file (from my original view_file)
    target = """    try:
        import asyncio
        raw = await asyncio.to_thread(
            chat_completion,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=3200,
            temperature=0.12,
        )
        parsed = clean_json_response(raw)
    except Exception as exc:
        logger.warning("Question analysis failed; using deterministic fallback: %s", exc)
            "answer_type": infer_answer_type(question),
            "question_intent": f"Prepare a full-mark engineering exam answer for: {question}",
        }"""
        
    replacement = """    try:
        import asyncio
        raw = await asyncio.to_thread(
            chat_completion,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=3200,
            temperature=0.12,
        )
        parsed = clean_json_response(raw)
    except Exception as exc:
        logger.warning("Question analysis failed; using deterministic fallback: %s", exc)
        parsed = {
            "answer_type": infer_answer_type(question),
            "question_intent": f"Prepare a full-mark engineering exam answer for: {question}",
        }"""

    if target in content:
        content = content.replace(target, replacement)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Fixed syntax error successfully!")
    else:
        print("Could not find the exact broken target string!")

except Exception as e:
    print("Error:", e)
