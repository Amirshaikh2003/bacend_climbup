import asyncio
import json
from app.services.ai.question_analyzer import analyze_question
from app.services.ai.answer_generator import generate_answer_via_groq

async def main():
    try:
        q = "What is machine learning?"
        print("Analyzing...")
        analysis = await analyze_question(q)
        print("Analysis done:", list(analysis.keys()))
        print("Generating answer...")
        ans = generate_answer_via_groq(q, analysis)
        print("Answer done. Success?", not ans.get("is_error"))
        print(str(ans)[:500])
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
