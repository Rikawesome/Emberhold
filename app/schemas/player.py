import uuid

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str



class RegisterResponse(BaseModel):
    player_id: uuid.UUID
    username: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
