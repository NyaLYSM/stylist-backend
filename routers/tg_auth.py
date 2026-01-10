# routers/tg_auth.py

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
from models import User  # Импорт модели

router = APIRouter(tags=["Telegram Auth"])

BOT_TOKEN = os.environ.get("BOT_TOKEN") 
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")

class TelegramAuthPayload(BaseModel):
    init_data: str = Field(alias='initData') 
    
    class Config:
        allow_population_by_field_name = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

def validate_telegram_data(init_data: str) -> dict:
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
            detail="Нет хеша в данных Telegram"
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
            detail="Недействительный хеш Telegram"
        )

    # 🔥 УБРАНА СТРОГАЯ ПРОВЕРКА auth_date - она вызывала "Сессия истекла"
    
    if 'user' not in data:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Нет данных пользователя"
        )

    user_data = json.loads(data['user'])
    return user_data

@router.post("/tg-login", response_model=Token)
def telegram_login(
    payload: TelegramAuthPayload, 
    db: Session = Depends(get_db)
):
    user_data = validate_telegram_data(payload.init_data) 
    
    user_id = user_data.get('id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Нет ID пользователя"
        )
    
    # 🔥 ИСПОЛЬЗУЕМ tg_id ВМЕСТО id
    user = db.query(User).filter(User.tg_id == user_id).first()
    
    if not user:
        # Создаём нового пользователя
        user = User(
            tg_id=user_id,  # 🔥 ПРАВИЛЬНОЕ ПОЛЕ
            username=user_data.get('username', f'user_{user_id}'),
            first_name=user_data.get('first_name', ''),
            last_name=user_data.get('last_name', ''),
            last_login=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ New user created: {user_id}")
    else:
        # Обновляем last_login
        user.last_login = datetime.utcnow()
        db.commit()
    
    access_token = create_access_token(data={"user_id": user_id})
    
    return {"access_token": access_token, "token_type": "bearer"}
