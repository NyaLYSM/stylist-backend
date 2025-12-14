import requests
from requests.exceptions import ConnectionError, HTTPError

# Локальный адрес для вашего сервиса на ПК
CLIP_URL = "https://bba4bk1mjete8virsbkp.containers.yandexcloud.net"

def clip_check(image_url: str, title: str) -> dict:
    """Проверяет изображение через внешний CLIP-сервис и всегда возвращает словарь."""
    try:
        r = requests.post(CLIP_URL, json={
            "image_url": image_url,
            "title": title
        }, timeout=5)
        r.raise_for_status() # Выбросит исключение для 4xx/5xx ошибок
        return r.json() # Ожидаем {"ok": bool, "reason": str}
        
    except ConnectionError:
        # Ошибка подключения к 127.0.0.1:8001 (CLIP не запущен на Render)
        return {"ok": False, "reason": "Connection Error: Не удалось подключиться к CLIP-сервису на 127.0.0.1:8001. Сервис недоступен или не запущен на Render."}
        
    except HTTPError as e:
        # Ошибка HTTP (4xx/5xx) от самого CLIP-сервиса
        return {"ok": False, "reason": f"CLIP-сервис вернул ошибку: {e}"}

    except Exception as e:
        # Другая ошибка (например, таймаут, ошибка JSON)
        return {"ok": False, "reason": f"Неизвестная ошибка при проверке CLIP: {e}"}
