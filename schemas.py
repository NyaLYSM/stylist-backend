# stylist-backend/schemas.py

from pydantic import BaseModel

class APILogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
