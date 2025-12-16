import os
from typing import Optional
from jose import jwt, JWTError
from fastapi import Header, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED 

# Конфигурация JWT (Скопировано из auth.py)
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") 
ALGORITHM = "HS256"

if not SECRET_KEY:
    # Важно: На Render установите переменную JWT_SECRET_KEY!
    raise ValueError("JWT_SECRET_KEY не установлен в переменных окружения. Аутентификация невозможна.")


def decode_access_token(token: str) -> Optional[dict]:
    """Декодирует и проверяет JWT-токен."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user_id(Authorization: str = Header(..., description="Bearer <token>")) -> int:
    """Извлекает и проверяет токен, возвращает user_id (tg_id)."""
    
    if not Authorization or not Authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, 
            detail="Неверный формат токена. Ожидается 'Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    token = Authorization.split(" ")[1] 
    payload = decode_access_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, 
            detail="Недействительный или просроченный токен.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user_id = payload.get("user_id") 
    
    if user_id is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, 
            detail="Токен не содержит user_id.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user_id
