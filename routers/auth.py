import os
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from jose import jwt

# Эти импорты могут быть удалены, так как они используются только в удаленных функциях, 
# но для порядка можем оставить только те, что не вызывают циклов.
# from fastapi import Header, HTTPException, Depends 
# from starlette.status import HTTP_401_UNAUTHORIZED 


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

# ВНИМАНИЕ: ФУНКЦИИ decode_access_token И get_current_user_id УДАЛЕНЫ ОТСЮДА
