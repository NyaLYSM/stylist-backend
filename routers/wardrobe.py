# routers/wardrobe.py

import os
import requests 
import asyncio 
from datetime import datetime 
from io import BytesIO 
from PIL import Image 

from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form, Query
from pydantic import BaseModel 
from sqlalchemy.orm import Session

# Абсолютные импорты
from database import get_db
from models import WardrobeItem 
from utils.storage import delete_image, save_image
from utils.validators import validate_name
from .dependencies import get_current_user_id 

router = APIRouter(tags=["Wardrobe"])

# --- СХЕМЫ ---
class ItemUrlPayload(BaseModel):
    name: str
    url: str

class ItemResponse(BaseModel):
    id: int
    name: str
    image_url: str
    source_type: str
    created_at: datetime 
    
    class Config:
        from_attributes = True

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def validate_image_bytes(file_bytes: bytes):
    MAX_SIZE_MB = 10

    if len(file_bytes) > MAX_SIZE_MB * 1024 * 1024:
        return False, f"Размер файла превышает {MAX_SIZE_MB} МБ."

    try:
        with Image.open(BytesIO(file_bytes)) as img:
            img.verify()  # только проверка
            if img.format not in ['JPEG', 'PNG', 'GIF', 'WEBP']:
                return False, "Неподдерживаемый формат изображения."
    except Exception:
        return False, "Файл не является действительным изображением."

    return True, None


def download_and_save_image_sync(url: str, name: str, user_id: int, item_type: str, db: Session):
    try:
        response = requests.get(url, timeout=10) 
        response.raise_for_status() 
    except requests.exceptions.RequestException as e:
        raise HTTPException(400, f"Ошибка скачивания фото: {str(e)}")
        
    file_bytes = response.content
    valid, error = validate_image_bytes(file_bytes) 
    if not valid:
        raise HTTPException(400, f"Ошибка валидации файла: {error}")

    try:
        # Используем локальную константу IMAGE_SUBDIR
        filename = f"url_{user_id}_{int(datetime.now().timestamp())}.jpg"
        final_url = save_image(filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения на диск: {str(e)}")

    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        source_type=item_type, # Исправлено название поля под модель
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

# --- РОУТЫ ---

@router.get("/items", response_model=list[ItemResponse]) 
def get_wardrobe_items(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.created_at.desc()).all()
    return items if items else []

@router.post("/add-file", response_model=ItemResponse)
async def add_item_file(
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    # 1. Валидация имени
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")

    # 2. Читаем файл
    file_bytes = await file.read()
    await file.close()

    # 3. Валидация изображения
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        raise HTTPException(400, f"Ошибка файла: {error}")

    # 4. Сохраняем ТОЛЬКО bytes
    try:
        filename = f"user_{user_id}_{int(datetime.utcnow().timestamp())}.png"
        final_url = save_image(filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    # 5. Сохраняем в БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        source_type="file",
        image_url=final_url,
        created_at=datetime.utcnow()
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return item
    
# 2. Добавление по URL (Ручной)
@router.post("/add-manual-url", response_model=ItemResponse)
async def add_item_by_manual_url(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_and_save_image_sync(payload.url, payload.name, user_id, "url_manual", db)
    )

# 3. Добавление по URL (Маркетплейс)
@router.post("/add-marketplace", response_model=ItemResponse)
async def add_item_by_marketplace(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_and_save_image_sync(payload.url, payload.name, user_id, "url_marketplace", db)
    )

@router.delete("/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(404, detail="Вещь не найдена")

    try:
        delete_image(item.image_url)
    except:
        pass # Игнорируем ошибки удаления файла, главное удалить из БД

    db.delete(item)
    db.commit()
    return {"status": "success"}



