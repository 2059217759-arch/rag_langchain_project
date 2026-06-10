from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    session_id: str


class ClearRequest(BaseModel):
    session_id: str


class StatusResponse(BaseModel):
    success: bool
    message: str


class UploadResponse(BaseModel):
    success: bool
    message: str
    parent_count: int = 0
    child_count: int = 0
