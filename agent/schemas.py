from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str | None = None
    role: str = "user"
    token: str = ""


class ChatResponse(BaseModel):
    reply: str
    session_id: str
