import asyncio
import json
from app.services.ai.question_analyzer import analyze_question
from app.services.ai.answer_generator import generate_answer_via_gemini_strict

async def test():
    print("Testing question analyzer...")
    analysis = await analyze_question('Explain OSI Model', marks=5)
    print("Analyzer Output:", json.dumps(analysis)[:200] + "...")
    
    print("Testing answer generator...")
    ans = generate_answer_via_gemini_strict('Explain OSI Model', analysis)
    print("Generator Output:", json.dumps(ans)[:500] + "...")

if __name__ == "__main__":
    asyncio.run(test())
