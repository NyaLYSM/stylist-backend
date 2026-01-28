# utils/clip_client.py
import logging
import requests
from io import BytesIO

logger = logging.getLogger(__name__)

# СЮДА НУЖНО ВПИСАТЬ IP ВАШЕГО ЯНДЕКС ОБЛАКА
# Его можно найти в консоли Yandex Cloud (раздел Compute Cloud -> Виртуальные машины -> Публичный IPv4)
CLIP_SERVICE_URL = "http://ВАШ_IP_ЯНДЕКС_ОБЛАКА:8001"

def rate_image_relevance(image, product_name: str) -> float:
    """
    Отправляет картинку на сервер в Яндекс Облако для оценки (0-100).
    """
    try:
        # Конвертируем PIL Image в байты для отправки по HTTP
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format='JPEG')
        img_byte_arr.seek(0)

        files = {'file': ('image.jpg', img_byte_arr, 'image/jpeg')}
        data = {'text': product_name}

        # Отправляем запрос на новый эндпоинт /rate
        response = requests.post(
            f"{CLIP_SERVICE_URL}/rate", 
            files=files, 
            data=data, 
            timeout=10
        )
        
        if response.status_code == 200:
            return float(response.json().get("score", 50.0))
        
        logger.warning(f"⚠️ CLIP Cloud returned error: {response.status_code}")
        return 50.0
    except Exception as e:
        logger.error(f"❌ Connection to Yandex Cloud CLIP failed: {e}")
        return 50.0

def clip_check_clothing(image_url: str) -> dict:
    """Старая функция для совместимости"""
    try:
        r = requests.post(f"{CLIP_SERVICE_URL}/check-clothing", json={"image_url": image_url}, timeout=15)
        return r.json()
    except:
        return {"ok": True}
