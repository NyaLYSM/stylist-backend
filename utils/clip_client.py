# utils/clip_client.py
import requests
import logging

logger = logging.getLogger(__name__)

CLIP_URL = "http://127.0.0.1:8001"

def clip_check_clothing(image_url: str) -> dict:
    try:
        r = requests.post(
            f"{CLIP_URL}/check-clothing",
            json={"image_url": image_url},
            timeout=15
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }

def clip_classify_clothing(image_url: str) -> dict:
    """
    Классифицирует тип одежды, цвет, стиль
    Возвращает: {"success": bool, "type": {...}, "color": {...}, "style": {...}}
    """
    try:
        r = requests.post(
            f"{CLIP_URL}/classify-clothing",
            json={"image_url": image_url},
            timeout=15
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"CLIP classify-clothing error: {e}")
        return {"success": False, "error": str(e)}

def clip_generate_name(image_url: str) -> dict:
    """
    Генерирует умное название одежды
    Возвращает: {"success": bool, "name": str, "confidence": float}
    """
    try:
        r = requests.post(
            f"{CLIP_URL}/generate-name",
            json={"image_url": image_url},
            timeout=15
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"CLIP generate-name error: {e}")
        return {"success": False, "error": str(e), "name": "Покупка"}

def check_clip_service() -> bool:
    """Проверяет доступность CLIP сервиса"""
    try:
        r = requests.get(f"{CLIP_URL}/health", timeout=3)
        return r.status_code == 200
    except:
        return False
