from typing import List, Optional
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the sender: 'user' or 'assistant'")
    content: str = Field(..., description="The message content")

class ChatRequest(BaseModel):
    subject: Optional[str] = Field(None, description="The subject context (e.g. Operating Systems)")
    context: Optional[str] = Field(None, description="The specific topic or question context")
    messages: List[ChatMessage] = Field(..., description="Conversation history including the latest user message")

class ChatResponse(BaseModel):
    success: bool
    reply: str
