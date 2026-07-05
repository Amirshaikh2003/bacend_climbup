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
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
    OPENROUTER_MODEL_FALLBACK: str = os.getenv(
        "OPENROUTER_MODEL_FALLBACK",
        "deepseek/deepseek-r1-distill-llama-70b",
    )
    TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
settings = Settings()
