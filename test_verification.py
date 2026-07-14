import asyncio
from app.services.ai.answer_verifier import verify_student_answer

async def run_test():
    q = "What is the primary function of the OSI Network Layer?"
    a = "Batman is the best superhero ever lolol"
    print("Testing verification directly...")
    result = verify_student_answer(question=q, answer=a)
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(run_test())
