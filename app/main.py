from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.answer import router as answer_router


app = FastAPI(
    title="AI Engineering Platform",
    description=(
        "Question paper creation, answer generation, "
        "and Supabase storage API"
    ),
    version="1.0.0",
)


allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    answer_router,
    prefix="/api",
    tags=["Question Papers and Answers"],
)


@app.get("/", tags=["System"])
async def root():
    return {
        "success": True,
        "message": "AI Engineering Platform backend is running",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "create_question_paper": "/api/question-paper",
            "extract_questions": "/api/extract-questions",
            "generate_answer": "/api/answer",
            "demo_answer": "/api/generate-answer",
            "answer_analyzer": "/api/answer-analyzer",
        },
    }


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "success": True,
        "status": "ok",
        "service": "AI Engineering Platform",
        "version": "1.0.0",
    }
