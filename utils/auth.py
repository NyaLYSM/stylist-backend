import os
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Header, HTTPException, Depends
from starlette.status import HTTP_401_UNAUTHORIZED

# 1. Конфигурация
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY не установлен!")

# 2. Утилиты для паролей и токенов
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

# 3. Функция защиты роутов (ИСПРАВЛЕННАЯ)
def get_current_user_id(Authorization: Optional[str] = Header(None, description="Bearer <token>")) -> int:
    # Если заголовок не пришел вообще -> 401
    if not Authorization:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация (заголовок Authorization отсутствует)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Если формат неверный -> 401
    if not Authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Неверный формат токена. Ожидается 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = Authorization.split(" ")[1]
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Недействительный или истекший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Токен не содержит user_id")

    return user_id
