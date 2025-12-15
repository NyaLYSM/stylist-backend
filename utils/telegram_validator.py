# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os 
from urllib.parse import unquote_plus
from typing import Optional, Tuple, Dict, Any
import time 

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN") 
MAX_AUTH_DATE_SKEW_SECONDS = 3600 # Допустимое время жизни данных (1 час)

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# =================================================================


def validate_init_data(init_data: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Валидирует строку initData.
    Возвращает (user_id, user_data) при валидной подписи, иначе None.
    """
    
    secret_key = hmac.new(
        'WebAppData'.encode('utf-8'), 
        BOT_TOKEN.encode('utf-8'), 
        hashlib.sha256
    ).digest()
    
    check_params = []
    signature = None
    user_data = None # Теперь храним все данные пользователя
    auth_date = None
    
    # 1. Разбираем строку init_data
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        decoded_value = unquote_plus(value) 

        if key == 'hash':
            signature = value
        else:
            check_params.append(f"{key}={decoded_value}")
            
        if key == 'auth_date':
            try:
                auth_date = int(decoded_value)
            except ValueError:
                pass 
        
        # Извлекаем user ID и ДАННЫЕ
        if key == 'user':
            try:
                user_data = json.loads(decoded_value)
            except Exception:
                pass 

    if not signature or not user_data or 'id' not in user_data:
        # Не удалось найти подпись или данные пользователя
        return None 
    
    tg_user_id = user_data['id']
    
    # 2. Сортируем пары по алфавиту и объединяем через \n
    check_params.sort()
    data_check_string = '\n'.join(check_params)
    
    # 3. Вычисляем HMAC-SHA256 хеш (логи удалены для чистоты, так как они сработали)
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # 4. Проверка хеша
    if not hmac.compare_digest(hmac_hash, signature):
        return None
    
    # 5. Проверка времени (если хеш прошел)
    if auth_date:
        current_time_utc = int(time.time())
        age_seconds = current_time_utc - auth_date
        
        if age_seconds > MAX_AUTH_DATE_SKEW_SECONDS or age_seconds < -60: 
            return None
            
    # Успех: возвращаем ID и полный словарь данных пользователя
    return tg_user_id, user_data
