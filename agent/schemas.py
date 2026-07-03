from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
