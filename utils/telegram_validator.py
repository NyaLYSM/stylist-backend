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
MAX_AUTH_DATE_SKEW_SECONDS = 3600 # Допустимое время жизни данных (1 час)

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# =================================================================


def validate_init_data(init_data: str) -> Optional[int]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int), если данные валидны.
    """
    
    # 1. КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ключ для подписи
    # HMAC-SHA256 токена бота, используя 'WebAppData' как ключ HMAC.
    secret_key = hmac.new(
        'WebAppData'.encode('utf-8'), 
        BOT_TOKEN.encode('utf-8'), 
        hashlib.sha256
    ).digest()
    
    check_params = []
    signature = None
    user_id = None
    auth_date = None
    
    # 2. Разбираем строку init_data
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        # URL-декодируем значение
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
                # Если JSON невалиден, это признак невалидных данных
                pass 

    if not signature:
        print("DEBUG: Signature (hash) not found in init_data.")
        return None 
    
    # 3. Сортируем пары по алфавиту и объединяем через \n
    check_params.sort()
    data_check_string = '\n'.join(check_params)
    
    # =================================================================
    # !!! КРИТИЧЕСКИЙ ЛОГ: Показывает, что именно хешируется
    # =================================================================
    print(f"DEBUG HASH STRING: {data_check_string}")
    
    
    # 4. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # 5. Проверка хеша
    if not hmac.compare_digest(hmac_hash, signature):
        # Дополнительная информация в логах, если хеш не совпал
        print(f"DEBUG HASH FAILURE: Computed Hash: {hmac_hash}")
        print(f"DEBUG HASH FAILURE: Received Hash: {signature}")
        return None
    
    # 6. Проверка времени (если хеш прошел)
    if auth_date:
        current_time_utc = int(time.time())
        age_seconds = current_time_utc - auth_date
        
        print(f"DEBUG TIME: Auth Date: {auth_date} (TG time), Current UTC: {current_time_utc} (Server time), Age: {age_seconds} seconds")
        
        # Если данные слишком старые или будущее время (расхождение)
        if age_seconds > MAX_AUTH_DATE_SKEW_SECONDS or age_seconds < -60: 
            print(f"DEBUG TIME: ⚠️ Хеш пройден, но данные просрочены ({age_seconds}s).")
            return None
            
    # 7. Успех
    if user_id is not None:
        print(f"DEBUG SUCCESS: Hash passed! User ID: {user_id}")
        return user_id
    
    return None
