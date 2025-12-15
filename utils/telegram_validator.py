# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os 
from urllib.parse import unquote
from typing import Optional, Tuple, Dict, Any # <-- ИЗМЕНЕНИЕ

BOT_TOKEN = os.getenv("BOT_TOKEN") 

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# ИЗМЕНЕНИЕ: Возвращает кортеж (ID, данные пользователя)
def validate_init_data(init_data: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int) и его данные (Dict), если подпись валидна.
    """
    
    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильный ключ для подписи Telegram
    secret_key = hmac.new(
        'WebAppData'.encode('utf-8'), 
        BOT_TOKEN.encode('utf-8'), 
        hashlib.sha256
    ).digest()
    
    data_check_string = []
    signature = None
    user_obj = None 
    tg_user_id = None
    
    # 1. Разбираем строку init_data на пары ключ=значение
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        if key == 'hash':
            signature = value
        else:
            # Важно: собираем пары в виде key=value (без URL-декодирования)
            data_check_string.append(f"{key}={value}")
            
            # Извлекаем и сохраняем данные пользователя
            if key == 'user':
                try:
                    # user-объект приходит в URL-декодированном виде
                    user_json = unquote(value)
                    user_obj = json.loads(user_json) # <-- СОХРАНЯЕМ ОБЪЕКТ
                    tg_user_id = int(user_obj.get("id"))
                except Exception:
                    pass 

    if not signature or not tg_user_id or not user_obj:
        return None 
    
    # 2. Сортируем пары по алфавиту и объединяем их через \n (ключевой момент)
    data_check_string.sort()
    data_check_string = '\n'.join(data_check_string)
    
    # 3. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()
    
    # 4. Сравниваем вычисленный хеш с подписью из initData
    if hmac.compare_digest(hmac_hash, signature):
        # 5. Возвращаем ID и полный словарь данных пользователя
        return tg_user_id, user_obj # <-- ИЗМЕНЕНИЕ
    
    return None
