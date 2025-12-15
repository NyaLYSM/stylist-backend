# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os 
from urllib.parse import unquote_plus # Используем unquote_plus для URL-декодирования
from typing import Optional

# Прямое получение токена из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN") 

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# (DEBUG-логи можно удалить, т.к. мы подтвердили, что токен читается)
# print(f"DEBUG: BOT_TOKEN READ (Length): {len(BOT_TOKEN)}")
# print(f"DEBUG: BOT_TOKEN READ (First 5 chars): {BOT_TOKEN[:5]}")


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
    
    # 1. Разбираем строку init_data на пары ключ=значение
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        # КРИТИЧЕСКИЙ ШАГ: URL-декодируем значение (важно для 'user' и других полей)
        decoded_value = unquote_plus(value) 

        if key == 'hash':
            signature = value
        else:
            # Для хеширования пары должны быть key=DECODED_VALUE
            check_params.append(f"{key}={decoded_value}")
        
        # Извлекаем user ID (для возврата)
        if key == 'user':
            try:
                # user-объект приходит в виде JSON
                user_data = json.loads(decoded_value)
                user_id = user_data.get('id')
            except Exception:
                pass # Если user= невалидный JSON, игнорируем, но user_id остается None

    if not signature:
        return None 
    
    # 2. Сортируем пары по алфавиту и объединяем их через \n (КЛЮЧЕВОЙ МОМЕНТ)
    check_params.sort()
    data_check_string = '\n'.join(check_params)
    
    # 3. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'), # Кодируем строку в UTF-8
        hashlib.sha256
    ).hexdigest()
    
    # 4. Сравниваем вычисленный хеш с подписью и убеждаемся, что есть ID
    # Используем compare_digest для защиты от атак по времени
    if hmac.compare_digest(hmac_hash, signature) and user_id is not None:
        return user_id
    
    return None
