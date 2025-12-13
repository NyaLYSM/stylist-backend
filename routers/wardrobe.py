# routers/wardrobe.py
import io 
import requests
import filetype
import os 
import json 
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session
from PIL import Image 

from database import get_db
from models import WardrobeItem
from utils.clip_helper import clip_check 

router = APIRouter()

# ================== CONFIG ==================
# Простой хостинг, не требующий ключей и не использующий Cloudflare
POSTIMG_UPLOAD_URL = "https://postimg.cc/upload"

# ================== LIMITS ==================
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png") 

# ================== BLACKLIST/WHITELIST (Остаются без изменений) ==================
BLACKLIST_WORDS = {
    "porn", "sex", "xxx", "nsfw", "нелегаль", "запрет"
}
WHITELIST_KEYWORDS = {
    "футболка","лонгслив","рубашка","поло","майка","топ","кроп","блузка",
    "платье","сарафан","комбинация",
    "джинсы","брюки","штаны","чиносы","леггинсы","лосины",
    "шорты","бермуды",
    "юбка","мини","миди","макси",
    "свитер","джемпер","кофта","кардиган","худи","толстовка","свитшот",
}

# ================== UTILS (Остаются без изменений) ==================
def get_image_kind(data: bytes) -> Optional[filetype.Type]:
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

def upload_to_postimg(data: bytes, filename: str) -> str:
    """Перекодирует изображение в стандартный JPEG и загружает на Postimages."""

    # 1. Загружаем байты в Pillow для принудительного перекодирования в JPEG
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения (Pillow): {e}")

    # 2. Конвертируем в RGB и сохраняем в новый байтовый буфер как JPEG
    output_buffer = io.BytesIO()
    if image.mode != 'RGB':
        image = image.convert('RGB')

    image.save(output_buffer, format="JPEG", quality=90) 
    processed_data = output_buffer.getvalue() # Получаем сырые байты

    # 3. Отправляем данные на Postimages

    # Postimages принимает файл в поле 'file' и использует специальный URL для прямых ссылок
    files = {
        'file': (filename, processed_data, 'image/jpeg')
    }

    # Мы используем прямой URL загрузки, а не их API, чтобы избежать ключей.
    # Это должно дать нам JSON-ответ.
    data_payload = {
        'upload': 'true',
        'api': 'true',
        'nsfw': '0'
    }

    try:
        response = requests.post(POSTIMG_UPLOAD_URL, files=files, data=data_payload, timeout=30) 
        response.raise_for_status() 

        result = response.json()

        # Postimages возвращает ключ 'url_key' и 'hash' для формирования прямой ссылки
        if result.get('hash') and result.get('url_key'):
            # Формируем прямую ссылку на изображение: i.postimg.cc/<hash>/<url_key>.jpeg
            image_hash = result['hash']
            url_key = result['url_key']
            # Сохраняем всегда в JPEG, так как мы его перекодировали
            final_url = f"https://i.postimg.cc/{url_key}/{image_hash}.jpeg"
            return final_url
        else:
            error_detail = result.get('message', response.text)
            raise Exception(f"Неожиданный ответ Postimages: {error_detail}")

    except requests.exceptions.RequestException as e:
        # Логика обработки ошибок, аналогичная предыдущим
        ptp_error_detail = "Неизвестная ошибка Postimages."

        if hasattr(e, 'response') and e.response is not None:
             response_text = e.response.text

             print(f"DEBUG: Full Postimages response: {response_text}") 

             raise HTTPException(
                status_code=400, 
                detail=f"Ошибка загрузки фото. Ответ Postimages: {response_text}"
            )

        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Postimages. Сервер недоступен или таймаут. {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Postimages: {e}")

# ================== ENDPOINTS ==================

# ... (Роуты /list, /add остаются без изменений) ...

@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Логика проверки файла и имени остается без изменений
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла (требуется JPEG/PNG).")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат.")

    ext = image_kind.extension
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"

    # *** ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ POSTIMAGES ***
    final_url = upload_to_postimg(data, fname) 

    # Проверка CLIP 
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        raise HTTPException(400, clip_result["reason"])

    # Сохранение в базу данных
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

@router.get("/list")
def list_items(user_id: int, db: Session = Depends(get_db)):
    """Получить список всех вещей пользователя."""
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    
    # Преобразование объектов SQLAlchemy в словари для корректного ответа FastAPI
    # (Это нужно, если вы не используете Pydantic)
    result = []
    for item in items:
        result.append({
            "id": item.id,
            "user_id": item.user_id,
            "name": item.name,
            "item_type": item.item_type,
            "image_url": item.image_url,
            "created_at": item.created_at.isoformat()
        })
        
    return {"status": "ok", "items": result}

@router.delete("/delete")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    """Удалить вещь из гардероба по ID."""
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id, 
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(404, "Вещь не найдена или не принадлежит этому пользователю.")

    db.delete(item)
    db.commit()

    return {"status": "ok", "message": f"Вещь с ID {item_id} удалена."}
