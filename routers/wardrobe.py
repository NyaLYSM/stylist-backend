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

# ================== IMAGUR CONFIG ==================
# Публичный Client ID для анонимной загрузки
IMGUR_CLIENT_ID = "944dd80d22dc9b4" # Стандартный, несекретный ID для анонимной загрузки
IMGUR_UPLOAD_URL = "https://api.imgur.com/3/image"

# ================== LIMITS ==================
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
# Оставляем только JPEG и PNG, так как Imgur может перекодировать
ALLOWED_MIMES = ("image/jpeg", "image/png") 

# ================== BLACKLIST ==================
BLACKLIST_WORDS = {
    "porn", "sex", "xxx", "nsfw", "нелегаль", "запрет"
}

# ================== HUGE WHITELIST ==================
WHITELIST_KEYWORDS = {
    "футболка","лонгслив","рубашка","поло","майка","топ","кроп","блузка",
    "платье","сарафан","комбинация",
    "джинсы","брюки","штаны","чиносы","леггинсы","лосины",
    "шорты","бермуды",
    "юбка","мини","миди","макси",
    "свитер","джемпер","кофта","кардиган","худи","толстовка","свитшот",
}

# ================== UTILS ==================
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
        
# *** НОВАЯ ФУНКЦИЯ: ЗАГРУЗКА НА IMGUR ***
def upload_to_imgur(data: bytes, filename: str) -> str:
    """Перекодирует изображение в стандартный JPEG и загружает на Imgur."""
    
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

    # 3. Отправляем данные на Imgur
    headers = {
        "Authorization": f"Client-ID {IMGUR_CLIENT_ID}"
    }
    
    # Imgur принимает файл как base64 или как multipart/form-data. 
    # multipart/form-data часто надежнее.
    files = {
        'image': ('file', processed_data, 'image/jpeg'),
        'type': (None, 'file'),
        'album': (None, 'false'), # Не загружать в альбом
        'title': (None, filename)
    }

    try:
        response = requests.post(IMGUR_UPLOAD_URL, files=files, headers=headers, timeout=15) 
        response.raise_for_status() 
        
        result = response.json()
        
        if result.get('success') and result.get('data'):
            # Ссылка на изображение
            return result['data']['link']
        else:
            # Imgur вернул ошибку, но с кодом 200 (редко, но бывает)
            error_detail = result.get('data', {}).get('error', 'Неизвестная ошибка Imgur')
            raise Exception(f"Ошибка Imgur API: {error_detail}")

    except requests.exceptions.RequestException as e:
        imgur_error_detail = "Неизвестная ошибка Imgur."
        
        if hasattr(e, 'response') and e.response is not None:
             response_text = e.response.text
             try:
                 json_data = e.response.json()
                 # Imgur возвращает { "data": { "error": "..." } } для 400 ошибок
                 imgur_error_detail = json_data.get('data', {}).get('error', response_text)
             except json.JSONDecodeError:
                 imgur_error_detail = response_text
                 
             print(f"DEBUG: Full Imgur response: {imgur_error_detail}") 
             
             raise HTTPException(
                status_code=400, 
                detail=f"Ошибка загрузки фото. Ответ Imgur: {imgur_error_detail}"
            )
        
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Imgur. Сервер недоступен или таймаут. {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Imgur: {e}")


# ================== ENDPOINTS ==================

@router.get("/list")
def get_wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    return {"status": "ok", "items": items}

@router.post("/add")
def add_item_url(
    user_id: int,
    name: str,
    image_url: str,
    item_type: str,
    db: Session = Depends(get_db)
):
    validate_name(name)

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type=item_type,
        image_url=image_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "ok", "item": item}

@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # MIME-проверка
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла (Imgur предпочитает JPEG/PNG).")

    # Проверка размера
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    # Проверка, что это изображение
    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат (проверено по байтам).")

    ext = image_kind.extension
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    
    # *** ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ IMGUR ***
    final_url = upload_to_imgur(data, fname) 

    # Проверка CLIP 
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
