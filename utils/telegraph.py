# utils/telegraph.py
import requests
from io import BytesIO
from typing import Tuple

TELEGRAPH_UPLOAD_URL = "https://telegra.ph/upload"
TELEGRAPH_HOST = "https://telegra.ph"


def upload_bytes_to_telegraph(file_bytes: bytes, filename: str) -> Tuple[bool, str]:
    """
    Загружает bytes файла на telegra.ph/upload и возвращает (True, url) или (False, error).
    """
    try:
        files = {
            'file': (filename, BytesIO(file_bytes), 'application/octet-stream')
        }
        resp = requests.post(TELEGRAPH_UPLOAD_URL, files=files, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Ожидается список: [{ "src": "/file/...." }]
        if isinstance(data, list) and len(data) > 0 and data[0].get("src"):
            src = data[0]["src"]
            # Если src уже абсолютный (редко) — аккуратно обработаем
            if src.startswith("http"):
                return True, src
            return True, TELEGRAPH_HOST + src
        else:
            return False, "Telegraph returned unexpected response"
    except Exception as e:
        return False, str(e)
