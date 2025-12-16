import os
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from jose import jwt
from fastapi import APIRouter, Depends, HTTPException, status # <-- ДОБАВЛЕНО
from pydantic import BaseModel # <-- ДОБАВЛЕНО
from sqlalchemy.orm import Session # <-- ДОБАВЛЕНО

# Предполагаем, что get_db и User/UserModel находятся в этих модулях:
from database import get_db 
# from models import User # Модель User закомментирована, чтобы избежать ошибок импорта, если ее нет

# ========================================
# 1. Pydantic Schemas (Схемы данных)
# ========================================

class UserCreate(BaseModel):
    """Схема для создания пользователя (регистрация)."""
    username: str
    password: str

class Token(BaseModel):
    """Схема ответа с JWT-токеном."""
    access_token: str
    token_type: str = "bearer"

# ========================================
# 2. Configuration & Utilities (Конфигурация и утилиты)
# ========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 

# Критическая проверка безопасности
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY не установлен в переменных окружения. JWT не может быть безопасно сгенерирован/проверен.")


def get_password_hash(password: str) -> str:
    """Хеширует пароль."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль."""
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

# ========================================
# 3. APIRouter Initialization (ИСПРАВЛЕНИЕ)
# ========================================
router = APIRouter() 
# ========================================


# ========================================
# 4. Endpoints (Роуты)
# ========================================

@router.post("/register", response_model=Token, summary="Регистрация нового пользователя")
def register_user(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    ВАЖНО: Добавьте здесь реальную логику БД:
    1. Проверить, что пользователь с таким именем не существует.
    2. Хешировать пароль с помощью get_password_hash.
    3. Создать запись пользователя в БД.
    4. Получить user_id нового пользователя.
    """

    # --- ЗАГЛУШКА (Placeholder) ---
    # В реальном приложении: user_id = db_user.id
    placeholder_user_id = 999999 
    
    access_token = create_access_token(
        data={"user_id": placeholder_user_id}
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login", response_model=Token, summary="Вход по логину/паролю")
def login_for_access_token(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    ВАЖНО: Добавьте здесь реальную логику БД:
    1. Найти пользователя по username.
    2. Проверить пароль с помощью verify_password.
    3. Если неверно, вызвать HTTPException 401.
    4. Получить user_id пользователя.
    """
    
    # --- ЗАГЛУШКА (Placeholder) ---
    # В реальном приложении: user_id = user.id
    placeholder_user_id = 999999 

    # --- Временная проверка для отладки ---
    if user_data.username != "test" or user_data.password != "password":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неправильное имя пользователя или пароль (используйте 'test'/'password' для заглушки)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"user_id": placeholder_user_id}
    )
    return {"access_token": access_token, "token_type": "bearer"}
