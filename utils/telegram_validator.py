# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os 
from urllib.parse import unquote_plus
from typing import Optional
import time 

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN") 
# Допустимое время жизни данных (например, 1 час)
MAX_AUTH_DATE_SKEW_SECONDS = 3600 

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# =================================================================


def validate_init_data(init_data: str) -> Optional[int]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int), если подпись валидна.
    """
    
    # Ключ для подписи - SHA256 хеш токена бота
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    
    check_params = []
    signature = None
    user_id = None
    auth_date = None
    
    # 1. Разбираем строку init_data
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        # КРИТИЧЕСКИЙ ШАГ: URL-декодируем значение (должен быть unquote_plus)
        decoded_value = unquote_plus(value) 

        if key == 'hash':
            signature = value
        else:
            # key=DECODED_VALUE для хеширования
            check_params.append(f"{key}={decoded_value}")
            
        if key == 'auth_date':
            try:
                auth_date = int(decoded_value)
            except ValueError:
                pass 
        
        # Извлекаем user ID
        if key == 'user':
            try:
                user_data = json.loads(decoded_value)
                user_id = user_data.get('id')
            except Exception:
                pass 

    if not signature:
        return None 
    
    # 2. Сортируем пары по алфавиту и объединяем через \n
    check_params.sort()
    data_check_string = '\n'.join(check_params)
    
    # =================================================================
    # !!! КРИТИЧЕСКИЙ ЛОГ: Показывает, что именно хешируется
    # =================================================================
    # Логируем только начало, чтобы не засорять логи (первые 100 символов)
    print(f"DEBUG HASH STRING: {data_check_string[:100]}...")
    
    
    # 3. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # 4. Проверка хеша
    if not hmac.compare_digest(hmac_hash, signature) or user_id is None:
        return None
        
    # 5. Проверка времени (если хеш прошел, но данные старые)
    if auth_date:
        current_time_utc = int(time.time())
        age_seconds = current_time_utc - auth_date
        
        print(f"DEBUG TIME: Auth Date: {auth_date}, Current UTC: {current_time_utc}, Age: {age_seconds} seconds")
        
        if age_seconds > MAX_AUTH_DATE_SKEW_SECONDS or age_seconds < -60:
            print(f"DEBUG TIME: ⚠️ Хеш пройден, но данные просрочены ({age_seconds}s). Возвращаем None.")
            return None
            
    return user_id
