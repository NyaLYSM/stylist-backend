# routers/wardrobe.py
import io
import requests
import filetype
import os 
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session

from database import get_db
from models import WardrobeItem
from utils.clip_helper import clip_check # Предполагаем, что этот импорт корректен

router = APIRouter()

# ================== LIMITS ==================
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png", "image/webp", "image/avif")

# ================== BLACKLIST ==================
BLACKLIST_WORDS = {
    "porn", "sex", "xxx", "nsfw", "нелегаль", "запрет"
}

# ================== HUGE WHITELIST ==================
WHITELIST_KEYWORDS = {
    # ... (список ключевых слов) ...
}

# ================== UTILS ==================
# *** ИСПРАВЛЕНО: Функция теперь возвращает объект filetype.Kind для надежного определения MIME ***
def get_image_kind(data: bytes) -> Optional[filetype.Type]:
    """Возвращает объект filetype.Type (ext и mime), если файл является разрешенным изображением."""
    kind = filetype.guess(data)
    if kind and kind.mime in ALLOWED_MIMES:
        return kind
    return None

def validate_name(name: str):
    if len(name.strip()) < 2:
        raise HTTPException(400, "Название должно быть длиннее 2 символов")
    for word in BLACKLIST_WORDS:
        if word in name.lower():
            raise HTTPException(400, "Название содержит запрещенные слова")
        
def upload_to_telegraph(data: bytes, filename: str, mime_type: str) -> str:
    """Загружает байты изображения в Telegra.ph, используя фактический MIME-тип."""
    
    # MIME-тип теперь гарантированно получен из заголовка файла
    files = {'file': (filename, data, mime_type)} 
    
    try:
        response = requests.post("https://telegra.ph/upload", files=files, timeout=10)
        response.raise_for_status() 
        
        result = response.json()
        
        if result and isinstance(result, list) and result[0].get('src'):
            return "https://telegra.ph" + result[0]['src']
        else:
            print(f"Telegraph upload failed. Unexpected response: {result}")
            error_detail = result.get('error', 'Неизвестный формат ошибки') if isinstance(result, dict) else response.text
            raise Exception(f"Некорректный или ошибочный ответ от Telegraph: {error_detail}")

    except requests.exceptions.RequestException as e:
        print(f"Telegraph upload failed (RequestError): {e}")
        
        # Улучшенное сообщение об ошибке для клиента
        detail_msg = "Ошибка Bad Request при отправке в Telegraph. Проверьте формат файла."
        if hasattr(e, 'response') and e.response is not None:
             detail_msg += f" Ответ Telegraph: {e.response.text}"
             raise HTTPException(status_code=400, detail=detail_msg)
        
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Telegraph. Сервер недоступен или таймаут.")
    except Exception as e:
        print(f"Telegraph upload failed (LogicError): {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Telegraph: {e}")

# ================== ENDPOINTS ==================

# ... (роуты /list, /add) ...

# *** ИСПРАВЛЕНО: Роут /upload теперь использует надежное определение MIME-типа ***
@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Проверка MIME-типа из клиента (первая, менее надежная линия обороны)
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    # *** КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем точные данные о файле из его байтов ***
    image_kind = get_image_kind(data) 
    
    if not image_kind:
        # Это сработает, если файл не JPEG/PNG/WebP/AVIF, даже если клиент сказал "image/jpeg"
        raise HTTPException(400, "Не изображение или неподдерживаемый формат (проверено по байтам).")

    final_mime_type = image_kind.mime
    ext = image_kind.extension
    # *** КОНЕЦ КРИТИЧЕСКОГО ИСПРАВЛЕНИЯ ***
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    
    # Теперь передаем надежный MIME-тип
    final_url = upload_to_telegraph(data, fname, final_mime_type) 

    # Проверка CLIP (предполагаем, что этот шаг корректен)
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        raise HTTPException(400, clip_result["reason"])

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="upload",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "ok", "item": item}

@router.delete("/{item_id}")
# ... (код функции delete_item) ...
def delete_item(
    item_id: int,
    user_id: int, 
    db: Session = Depends(get_db)
):
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или нет доступа")

    db.delete(item)
    db.commit()

    return {"status": "ok", "message": "Вещь успешно удалена"}
