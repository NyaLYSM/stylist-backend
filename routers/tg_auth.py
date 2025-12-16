import os
import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Импорт утилит для работы с БД и JWT
from database import get_db
from .auth import create_access_token # Теперь импортируем только функцию создания JWT
# from models import User # Закомментировано, так как файл User.py не предоставлен


# ========================================
# 1. КОНФИГУРАЦИЯ И ПРОВЕРКА ТОКЕНА
# ========================================

router = APIRouter(tags=["Telegram Auth"])

# Критически важно: Токен бота для валидации.
BOT_TOKEN = os.environ.get("BOT_TOKEN") 
if not BOT_TOKEN:
    # Приложение упадет при запуске, если нет токена
    raise ValueError("BOT_TOKEN environment variable not set. Telegram Auth cannot function.")

# ========================================
# 2. СХЕМА ДАННЫХ
# ========================================

class TelegramAuthPayload(BaseModel):
    """Схема для получения initData из фронтенда (POST-запрос)."""
    initData: str # Фронтенд передает initData

class Token(BaseModel):
    """Схема ответа с JWT-токеном."""
    access_token: str
    token_type: str = "bearer"

# ========================================
# 3. ЛОГИКА ВАЛИДАЦИИ (HMAC-SHA-256)
# ========================================

def validate_telegram_data(init_data: str) -> dict:
    """
    Валидирует Telegram Web App initData с помощью HMAC-SHA-256.
    
    Возвращает словарь данных пользователя (user_data).
    """
    
    data_check_string = []
    data = {}
    
    # 1. Парсинг init_data и сбор строки для проверки
    try:
        # Разбиваем на пары ключ=значение
        for param in init_data.split('&'):
            key, value = param.split('=', 1)
            # URL-декодирование значения
            data[key] = urllib.parse.unquote(value)
            
            # Собираем все поля, кроме 'hash', для проверки
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
    
    # 2. Сортировка и объединение строки для проверки (по алфавиту, через \n)
    data_check_string.sort()
    data_check_string = '\n'.join(data_check_string)
    
    # 3. Генерация секретного ключа: HMAC-SHA256(bot_token, 'WebAppData')
    secret_key = hmac.new(
        key=b'WebAppData', 
        msg=BOT_TOKEN.encode(), 
        digestmod=hashlib.sha256
    ).digest()
    
    # 4. Расчет ожидаемого хеша: HMAC-SHA256(secret_key, data_check_string)
    calculated_hash = hmac.new(
        key=secret_key, 
        msg=data_check_string.encode(), 
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # 5. Сравнение хешей
    if calculated_hash != check_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Недействительный хеш. Данные Telegram скомпрометированы."
        )

    # 6. Проверка срока действия (auth_date) - должно быть не старше 60 секунд
    if 'auth_date' in data:
        auth_date = int(data['auth_date'])
        current_time = int(datetime.now().timestamp())
        if current_time - auth_date > 60:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Сессия истекла. Пожалуйста, перезапустите бота."
            )
            
    # 7. Извлечение данных пользователя
    if 'user' not in data:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Данные Telegram не содержат user."
        )

    # 'user' - это JSON-строка, которую нужно распарсить
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
    user_data = validate_telegram_data(payload.initData)
    
    user_id = user_data.get('id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="В данных Telegram отсутствует ID пользователя."
        )
        
    # 2. Проверка/Создание пользователя в базе данных (Ваша логика)
    # 
    # Placeholder: имитируем работу с БД
    print(f"User ID from Telegram: {user_id}. Creating JWT.")

    # 3. Создание JWT-токена
    access_token = create_access_token(
        data={"user_id": user_id} 
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
