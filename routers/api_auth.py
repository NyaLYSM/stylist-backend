# stylist-backend/routers/api_auth.py

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Optional

# ИСПРАВЛЕНО: Заменены относительные импорты на абсолютные
from database import get_db
from models import User # Теперь импортируем из корневого models.py
from schemas import APILogin, Token # Предполагаем, что schemas.py находится в корне
from utils.auth import get_password_hash, verify_password, create_access_token
from utils.auth import get_current_user_id # Теперь импортируем из utils.auth

router = APIRouter(tags=["API Auth"])

@router.post("/register", response_model=Token)
def register_api_user(user_data: APILogin, db: Session = Depends(get_db)):
    # 1. Проверка, существует ли пользователь по username
    db_user = db.query(User).filter(User.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует.")
    
    # 2. Хешируем пароль
    hashed_password = get_password_hash(user_data.password)
    
    # 3. Создаем нового пользователя
    # CRITICAL FIX: Генерация уникального ОТРИЦАТЕЛЬНОГО tg_id для API-only пользователей
    # Находим наименьший (наиболее отрицательный) существующий ID API-пользователя
    last_api_tg_id = db.query(func.min(User.tg_id)).filter(User.tg_id < 0).scalar()
    # Если нет отрицательных ID, начинаем с -1, иначе -1 от самого отрицательного
    new_tg_id = (last_api_tg_id or 0) - 1
    
    # Приводим к BigInteger, чтобы не было ошибки типа
    new_tg_id = int(new_tg_id) 

    new_user = User(
        username=user_data.username, 
        hashed_password=hashed_password,
        tg_id=new_tg_id # Устанавливаем уникальный отрицательный ID
    ) 
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 4. Генерируем токен, используя новый tg_id
    access_token = create_access_token(data={"sub": new_user.username, "user_id": new_user.tg_id})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    # 1. Находим пользователя по имени
    user = db.query(User).filter(User.username == form_data.username).first()
    
    # Проверка: пользователь должен существовать И иметь хеш пароля
    if not user or not user.hashed_password:
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль.")

    # 2. Проверяем пароль
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль.")
    
    # 3. Генерируем токен
    access_token = create_access_token(data={"sub": user.username, "user_id": user.tg_id})
    return {"access_token": access_token, "token_type": "bearer"}
