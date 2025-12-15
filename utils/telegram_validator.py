# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os
from urllib.parse import unquote
from typing import Optional, Tuple, Dict, Any # <-- ДОБАВЛЕНО

BOT_TOKEN = os.getenv("BOT_TOKEN") 

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")

# Изменен тип возвращаемого значения
def validate_init_data(init_data: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int) и его данные (Dict), если подпись валидна.
    """
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ключ для подписи Telegram
    secret_key = hmac.new(
        'WebAppData'.encode('utf-8'), 
        BOT_TOKEN.encode('utf-8'), 
        hashlib.sha256
    ).digest()
    
    data_check_string = []
    signature = None
    user_data = None 
    tg_user_id = None
    
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        if key == 'hash':
            signature = value
        else:
            data_check_string.append(f"{key}={value}")
            
            # Извлекаем и сохраняем данные пользователя
            if key == 'user':
                try:
                    user_json = unquote(value)
                    user_data = json.loads(user_json)
                    tg_user_id = int(user_data.get("id"))
                except Exception:
                    pass 

    if not signature or not tg_user_id or not user_data:
        return None 
    
    data_check_string.sort()
    data_check_string = '\n'.join(data_check_string)
    
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if hmac.compare_digest(hmac_hash, signature):
        # Успех: возвращаем ID и полный словарь данных пользователя
        return tg_user_id, user_data
    
    return None
