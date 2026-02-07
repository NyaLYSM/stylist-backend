# utils/clip_client.py
import logging
import requests
from io import BytesIO

logger = logging.getLogger(__name__)

# Ссылка на ваш контейнер в Яндекс Облаке
CLIP_URL = "https://bba4bk1mjete8virsbkp.containers.yandexcloud.net"

def rate_image_relevance(image, product_name: str) -> float:
    """Отправляет картинку на скоринг в Яндекс Облако"""
    try:
        # Подготовка картинки
        img_byte_arr = BytesIO()
        image.save(img_byte_arr, format='JPEG')
        img_byte_arr.seek(0)

        files = {'file': ('image.jpg', img_byte_arr, 'image/jpeg')}
        data = {'text': product_name}

        # Мы стучимся в эндпоинт /rate (его нужно будет добавить в контейнер, см. ниже)
        # Если в контейнере пока только старый код, этот запрос выдаст 404
        response = requests.post(f"{CLIP_URL}/rate", files=files, data=data, timeout=60)
        
        if response.status_code == 200:
            return float(response.json().get("score", 50.0))
        
        logger.warning(f"⚠️ CLIP Cloud Error {response.status_code}: {response.text}")
        return 50.0
    except Exception as e:
        logger.error(f"❌ Connection to Yandex Cloud failed: {e}")
        return 50.0

def clip_check_clothing(image_url: str) -> dict:
    """Старая функция для обратной совместимости"""
    try:
        r = requests.post(f"{CLIP_URL}/check-clothing", json={"image_url": image_url}, timeout=15)
        return r.json()
    except:
        return {"ok": True}



