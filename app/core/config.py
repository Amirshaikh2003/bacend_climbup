from dotenv import load_dotenv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")




class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "AI_ENGINEERING_PLATFORM")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

    OPENROUTER_API_KEY: str | None = (
        os.getenv("OPENROUTER_API_KEY", "").strip()
        or os.getenv("OPENROUTER", "").strip()
        or None
    )
    OPENROUTER_MODELS_POOL: list[str] = [
        m.strip() for m in os.getenv(
            "OPENROUTER_MODELS_POOL",
            "meta-llama/llama-3.3-70b-instruct:free,qwen/qwen3-next-80b-a3b-instruct:free,google/gemma-4-31b-it:free,nousresearch/hermes-3-llama-3.1-405b:free"
        ).split(",") if m.strip()
    ]
    TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
    GROQ_API_KEY_2: str | None = os.getenv("GROQ_API_KEY_2")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_MODEL_FALLBACK: str = os.getenv("GROQ_MODEL_FALLBACK", "llama-3.1-8b-instant")
settings = Settings()
