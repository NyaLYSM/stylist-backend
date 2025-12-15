# stylist-backend/utils/telegram_validator.py

import hmac
import hashlib
import json
import os # ДОБАВЛЕНО: Импорт os для доступа к переменным окружения
from urllib.parse import unquote
from typing import Optional

# !!! ИСПРАВЛЕНИЕ: Прямое получение токена из окружения, чтобы избежать 
# проблемы с путем импорта из поддиректории
# from config import BOT_TOKEN # <-- УДАЛИТЬ
BOT_TOKEN = os.getenv("BOT_TOKEN") # <-- ДОБАВИТЬ

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Невозможно проверить initData Telegram.")

print(f"DEBUG: BOT_TOKEN READ (Length): {len(BOT_TOKEN)}")
print(f"DEBUG: BOT_TOKEN READ (First 5 chars): {BOT_TOKEN[:5]}")
    
def validate_init_data(init_data: str) -> Optional[int]:
    """
    Валидирует строку initData, полученную от Telegram WebApp, 
    и возвращает ID пользователя (int), если подпись валидна.
    """
    
    # Ключ для подписи - SHA256 хеш токена бота
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    
    # 1. Разбираем строку init_data на пары ключ=значение
    data_check_string = []
    signature = None
    
    # InitData приходит в формате key1=val1&key2=val2&hash=signature
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

    if not signature:
        return None 
    
    # 2. Сортируем пары по алфавиту и объединяем их через \n (ключевой момент)
    data_check_string.sort()
    data_check_string = '\n'.join(data_check_string)
    
    # 3. Вычисляем HMAC-SHA256 хеш
    hmac_hash = hmac.new(
        secret_key, 
        data_check_string.encode(), 
        hashlib.sha256
    ).hexdigest()
    
    # 4. Сравниваем вычисленный хеш с подписью из initData
    if hmac_hash == signature:
        # 5. Извлекаем user ID из initData
        user_data = next((item for item in init_data.split('&') if item.startswith('user=')), None)
        
        if user_data:
            try:
                # user-объект приходит в URL-декодированном виде
                # Здесь нужно unquote, чтобы получить чистый JSON
                user_json = unquote(user_data.split('=', 1)[1])
                user_obj = json.loads(user_json)
                return int(user_obj.get("id"))
            except Exception as e:
                print(f"Error parsing user ID from initData: {e}")
                return None 
        
        return None
    
    return None
