# routers/tg_auth.py (Полный и исправленный)

import os
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field # <--- ДОБАВЛЕНО Field
from sqlalchemy.orm import Session
from database import get_db
from .auth import create_access_token 
# from models import User 

# ========================================
# 1. КОНФИГУРАЦИЯ
# ========================================
router = APIRouter(tags=["Telegram Auth"])

BOT_TOKEN = os.environ.get("BOT_TOKEN") 
if not BOT_TOKEN:
    # Приложение упадет при запуске, если нет токена
    raise ValueError("BOT_TOKEN environment variable not set. Telegram Auth cannot function.")

# ========================================
# 2. СХЕМА ДАННЫХ (FIX: Используем initData, как ожидает фронтенд, 
# и убедимся, что она соответствует JSON-телу)
# ========================================

class TelegramAuthPayload(BaseModel):
    """
    Схема для получения initData из фронтенда.
    Pydantic по умолчанию ожидает snake_case, но фронтенд использует camelCase. 
    Мы используем "alias" (псевдоним) для гибкости.
    """
    initData: str = Field(alias='initData') 
    
    # Также проверим, если фронтенд по какой-то причине отправил snake_case
    class Config:
        allow_population_by_field_name = True # Позволяет использовать имя поля или псевдоним

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

# ========================================
# 3. ЛОГИКА ВАЛИДАЦИИ (HMAC-SHA-256) (без изменений)
# ========================================

def validate_telegram_data(init_data: str) -> dict:
    """
    Валидирует Telegram Web App initData с помощью HMAC-SHA-256.
    """
    
    data_check_string = []
    data = {}
    
    try:
        for param in init_data.split('&'):
            key, value = param.split('=', 1)
            data[key] = urllib.parse.unquote(value)
            
            if key != 'hash':
                data_check_string.append(f"{key}={urllib.parse.unquote(value)}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail=f"Неверный формат initData: {e}"
        )

    if 'hash' not in data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Инициализационные данные Telegram не содержат хеш."
        )

    check_hash = data.pop('hash')
    
    data_check_string.sort()
    data_check_string = '\n'.join(data_check_string)
    
    # Генерация ключа
    secret_key = hmac.new(
        key=b'WebAppData', 
        msg=BOT_TOKEN.encode(), 
        digestmod=hashlib.sha256
    ).digest()
    
    # Расчет хеша
    calculated_hash = hmac.new(
        key=secret_key, 
        msg=data_check_string.encode(), 
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if calculated_hash != check_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Недействительный хеш. Данные Telegram скомпрометированы."
        )

    # Проверка срока действия
    if 'auth_date' in data:
        auth_date = int(data['auth_date'])
        current_time = int(datetime.utcnow().timestamp()) # Используем utcnow() для безопасности
        if current_time - auth_date > 60:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Сессия истекла. Пожалуйста, перезапустите бота."
            )
            
    if 'user' not in data:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Данные Telegram не содержат user."
        )

    user_data = json.loads(data['user'])
    
    return user_data

# ========================================
# 4. ENDPOINT
# ========================================

@router.post("/tg-login", response_model=Token, summary="Авторизация через Telegram Web App")
def telegram_login(
    payload: TelegramAuthPayload, 
    db: Session = Depends(get_db)
):
    # 1. Валидация данных
    # FastAPI/Pydantic позаботится о том, чтобы получить initData из payload
    user_data = validate_telegram_data(payload.initData)
    
    user_id = user_data.get('id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="В данных Telegram отсутствует ID пользователя."
        )
        
    # 2. Логика БД (проверка/создание пользователя)
    # ...
    
    # 3. Создание JWT-токена
    access_token = create_access_token(
        data={"user_id": user_id} 
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
