# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os
from urllib.parse import unquote, unquote_plus # unquote_plus для корректного декодирования
from typing import Optional

# !!! ИСПРАВЛЕНИЕ: Прямое получение токена из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")
    
# =========================================================================
# ВРЕМЕННЫЙ ЛОГ ДЛЯ ПРОВЕРКИ (Можете удалить его после подтверждения)
print(f"DEBUG: BOT_TOKEN READ (Length): {len(BOT_TOKEN)}")
print(f"DEBUG: BOT_TOKEN READ (First 5 chars): {BOT_TOKEN[:5]}")
# =========================================================================


def validate_init_data(init_data: str) -> Optional[int]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int), если подпись валидна.
    """
    
    # Ключ для подписи - SHA256 хеш токена бота
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    
    # 1. Разбираем строку init_data на пары ключ=значение
    data_check_list = []
    signature = None
    user_id = None
    
    # InitData приходит в формате key1=val1&key2=val2&hash=signature
    for param in init_data.split('&'):
        try:
            key, value = param.split('=', 1)
        except ValueError:
            continue
            
        # URL-декодируем значение (нужно для корректного сравнения)
        decoded_value = unquote_plus(value) 

        if key == 'hash':
            signature = value
        else:
            # Важно: для проверки хеша, пары должны быть URL-декодированы 
            # (особенно 'user'), а затем отсортированы.
            data_check_list.append(f"{key}={decoded_value}")
        
        # Извлекаем user ID прямо здесь, если он есть
        if key == 'user':
            try:
                # user-объект приходит в виде URL-декодированного JSON
                user_data = json.loads(decoded_value)
                user_id = user_data.get('id')
            except Exception:
                pass # Пропускаем, если невалидный JSON

    if not signature:
        return None 
    
    # 2. Сортируем пары по алфавиту и объединяем их через \n (КЛЮЧЕВОЙ МОМЕНТ)
    # data_check_list содержит пары key=decoded_value (кроме hash)
    data_check_list.sort()
    data_check_string = '\n'.join(data_check_list)
    
    # 3. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode('utf-8'), # Кодируем строку в UTF-8
        hashlib.sha256
    ).hexdigest()
    
    # 4. Сравниваем вычисленный хеш с подписью из initData
    # Сравнение должно быть безопасным по времени (time-safe comparison)
    if hmac.compare_digest(hmac_hash, signature):
        # 5. Возвращаем user ID, если все ОК
        return user_id
    
    return None
