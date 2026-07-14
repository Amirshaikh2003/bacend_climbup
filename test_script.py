import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

from app.services.ai.question_analyzer import analyze_question
from app.services.ai.answer_generator import generate_answer_via_gemini_strict

async def test_generation():
    question = "Explain Quick Sort Algorithm with a flowchart."
    print(f"Testing Question: {question}")
    
    print("\n--- 1. Running Analyzer ---")
    analysis = await analyze_question(question, marks=8)
    print("Analyzer Output Success! Type:", type(analysis))
    
    print("\n--- 2. Running Answer Generator (Gemini Strict) ---")
    final_answer = generate_answer_via_gemini_strict(question, analysis, expected_marks=8)
    
    if final_answer.get("is_error"):
        print("\n[ERROR] Generation Failed!")
        print(json.dumps(final_answer, indent=2))
    else:
        print("\n[SUCCESS] Generation Completed!")
        blocks = final_answer.get("answer", [])
        for block in blocks:
            print(f"- {block.get('type')}: {block.get('title')}")
            if block.get('type') == 'mermaid':
                print("  Mermaid Content Snippet:", str(block.get('content'))[:100].replace('\n', '\\n'))

if __name__ == "__main__":
    asyncio.run(test_generation())
