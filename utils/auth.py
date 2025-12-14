import os
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from jose import jwt, JWTError

# ИСПРАВЛЕНИЕ: Эти импорты должны быть на уровне модуля (в начале файла)!
from fastapi import Header, HTTPException, Depends 
from starlette.status import HTTP_401_UNAUTHORIZED 


# 1. Конфигурация хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 2. Конфигурация JWT
# Ключ берется только из переменной окружения.
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 

# Критическая проверка безопасности
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY не установлен в переменных окружения. JWT не может быть безопасно сгенерирован/проверен.")


def get_password_hash(password: str) -> str:
    """Хеширует пароль перед сохранением в базу данных."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет введенный пароль с хешем из базы данных."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создает JWT-токен."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """Декодирует и проверяет JWT-токен."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

# Функция для защиты роутов
def get_current_user_id(Authorization: str = Header(..., description="Bearer <token>")) -> int:
    """Извлекает и проверяет токен, возвращает user_id (tg_id)."""
    
    # Внутренний импорт FastAPI удален
    
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
        
    # Мы ожидаем, что user_id (который является tg_id) будет в payload
    user_id = payload.get("user_id") 
    
    if user_id is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, 
            detail="Токен не содержит user_id.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user_id
