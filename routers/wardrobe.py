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
UPLOAD_DIR = "static/uploads" # Новая папка для хранения на сервере
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png") 

# Список запрещенных слов для валидации названия
BLACKLIST_WORDS = ["порно", "секс", "насилие", "guns", "оружие", "naked", "erotic", "porn"]

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
            
            
def save_locally(data: bytes, filename: str) -> str:
    """Перекодирует изображение в JPEG и сохраняет локально на сервере Render."""
    
    # 1. Создаем папку, если ее нет
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR)

    # 2. Загружаем байты в Pillow для принудительного перекодирования в JPEG
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения (Pillow): {e}")

    # 3. Конвертируем в RGB и сохраняем на диск
    output_path = os.path.join(UPLOAD_DIR, filename.replace(filename.split('.')[-1], 'jpeg'))
    
    if image.mode != 'RGB':
        image = image.convert('RGB')
        
    try:
        image.save(output_path, format="JPEG", quality=90)
        
        # Генерируем URL, который будет доступен через FastAPI
        return f"/static/uploads/{os.path.basename(output_path)}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла на сервере: {e}")

# ================== ENDPOINTS ==================

@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла (требуется JPEG/PNG).")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат.")

    # Используем новое расширение 'jpeg', так как мы принудительно перекодируем
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.jpeg"
    
    # *** ИСПОЛЬЗУЕМ ЛОКАЛЬНОЕ СОХРАНЕНИЕ ***
    final_url = save_locally(data, fname) 

    # Проверка CLIP
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        # Если CLIP выдает ошибку, то отклоняем
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
