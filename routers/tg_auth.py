# routers/tg_auth.py (Финальная версия с автосозданием пользователя)

import os
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database import get_db
from .auth import create_access_token 
from models import User  # 🔥 ДОБАВЛЕНО

# ========================================
# 1. КОНФИГУРАЦИЯ
# ========================================
router = APIRouter(tags=["Telegram Auth"])

BOT_TOKEN = os.environ.get("BOT_TOKEN") 
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set. Telegram Auth cannot function.")

# ========================================
# 2. СХЕМА ДАННЫХ (FIXED)
# ========================================

class TelegramAuthPayload(BaseModel):
    """
    Схема для получения initData из фронтенда.
    - Python имя поля: init_data (snake_case)
    - JSON имя поля: initData (camelCase)
    """
    init_data: str = Field(alias='initData') 
    
    class Config:
        allow_population_by_field_name = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

# ========================================
# 3. ЛОГИКА ВАЛИДАЦИИ (HMAC-SHA-256)
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
    
    secret_key = hmac.new(
        key=b'WebAppData', 
        msg=BOT_TOKEN.encode(), 
        digestmod=hashlib.sha256
    ).digest()
    
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

    if 'auth_date' in data:
        auth_date = int(data['auth_date'])
        current_time = int(datetime.utcnow().timestamp())
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
    user_data = validate_telegram_data(payload.init_data) 
    
    user_id = user_data.get('id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="В данных Telegram отсутствует ID пользователя."
        )
    
    # 🔥 АВТОСОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        # Создаём нового пользователя из данных Telegram
        user = User(
            id=user_id,  # Telegram ID
            username=user_data.get('username', f'user_{user_id}'),
            first_name=user_data.get('first_name', ''),
            last_name=user_data.get('last_name', ''),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ New user created: {user_id}")
    
    # Создание JWT-токена
    access_token = create_access_token(
        data={"user_id": user_id} 
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
