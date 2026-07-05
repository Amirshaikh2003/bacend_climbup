# AI Engineering Platform Backend

This backend is structured for an AI engineering platform with modular services.

## Structure

- `app/api/routes/answer.py` - answer route implementation
- `app/api/dependencies/` - shared dependency providers
- `app/core/` - configuration, database, prompts, and security helpers
- `app/services/` - AI, research, PDF, and rendering service modules
- `app/models/` - response and database models
- `app/schemas/` - request/response schemas
- `app/utils/` - logger, validator, and helper utilities
- `app/main.py` - FastAPI application entrypoint

## Environment

Place backend secrets in `backend/.env`. The React frontend must not contain
OpenRouter, Gemini, Tavily, SerpAPI, or Supabase service-role keys.

Required AI values:

- `OPENROUTER`
- `OPENROUTER_MODEL`
- `OPENROUTER_MODEL_FALLBACK`

## Quick start

1. Create a virtual environment
2. Install requirements: `pip install -r requirements.txt`
3. Run server: `uvicorn app.main:app --reload`

## Frontend GUI

The desktop Python GUI was replaced by the React TSX app in `../frontend`.
Run the backend first, then start the frontend:

1. `cd ../frontend`
2. `npm.cmd install`
3. `npm.cmd run dev`

The frontend calls `http://127.0.0.1:8000/api/extract-questions`,
`http://127.0.0.1:8000/api/question-paper`, and
`http://127.0.0.1:8000/api/answer`.
