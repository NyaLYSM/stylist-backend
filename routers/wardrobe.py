# routers/wardrobe.py (Полная исправленная версия)

import os
import requests 
from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form, Query # <-- Добавлен Query
from pydantic import BaseModel 
from sqlalchemy.orm import Session
from io import BytesIO 
from PIL import Image 
import asyncio 
from datetime import datetime # <-- FIX 1: ДОБАВИТЬ ЭТОТ ИМПОРТ

# Абсолютные импорты
from database import get_db
from models import WardrobeItem # Предполагается, что WardrobeItem импортирован
from utils.storage import delete_image, save_image
from utils.validators import validate_name

# *** ИСПРАВЛЕНИЕ: Импорт из нового модуля dependencies ***
from .dependencies import get_current_user_id
# ******************************************************

# ----------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ РОУТЕРА
# ----------------------------------------------------------------------
router = APIRouter(tags=["Wardrobe"]) # <-- FIX 2: ДОБАВИТЬ ЭТУ СТРОКУ

# ----------------------------------------------------------------------
# 1. SCHEMAS
# ----------------------------------------------------------------------
# Схема ответа для вещи в гардеробе
class ItemResponse(BaseModel):
    id: int
    name: str
    image_url: str
    source_type: str
    created_at: datetime 
    
    class Config:
        from_attributes = True

# Схема для принятия URL и имени
class ItemUrlPayload(BaseModel):
    name: str
    url: str

# ----------------------------------------------------------------------
# 2. HELPER FUNCTIONS
# ----------------------------------------------------------------------

# Если validate_image_bytes не определена в validators.py, используйте эту:
def validate_image_bytes(file_bytes: bytes):
    MAX_SIZE_MB = 10
    if len(file_bytes) > MAX_SIZE_MB * 1024 * 1024:
        return False, f"Размер файла превышает {MAX_SIZE_MB} МБ."
    
    try:
        img = Image.open(BytesIO(file_bytes))
        img.verify() 
        if img.format not in ['JPEG', 'PNG', 'GIF', 'WEBP']:
             return False, "Неподдерживаемый формат изображения."
    except Exception as e:
        return False, f"Файл не является действительным изображением: {e}"
        
    return True, None


# Синхронная функция, которая должна быть запущена в ThreadPoolExecutor
def download_and_save_image(url: str, name: str, user_id: int, source_type: str, db: Session):
    try:
        # 1. Загрузка изображения
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 2. Валидация
        file_bytes = response.content
        valid, error = validate_image_bytes(file_bytes)
        if not valid:
            raise HTTPException(400, f"Ошибка изображения: {error}")
            
        # 3. Сохранение и получение URL
        image_url = save_image(file_bytes, WardrobeItem.IMAGE_SUBDIR, user_id, name)
        
        # 4. Создание записи в БД
        new_item = WardrobeItem(
            user_id=user_id,
            name=name,
            image_url=image_url,
            source_type=source_type,
            created_at=datetime.utcnow() # Используем utcnow
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        
        return new_item
        
    except requests.exceptions.HTTPError as e:
        raise HTTPException(400, f"Ошибка при загрузке URL: {e}")
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Ошибка сервера при обработке изображения: {e}")

# ----------------------------------------------------------------------
# 3. ENDPOINTS
# ----------------------------------------------------------------------

# --- 1. Получение списка вещей (FIXED ENDPOINT) ---
@router.get("/items", response_model=list[ItemResponse], summary="Получить список вещей в гардеробе")
def get_wardrobe_items(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Возвращает все предметы гардероба текущего пользователя.
    """
    items = db.query(WardrobeItem).filter(
        WardrobeItem.user_id == user_id
    ).order_by(WardrobeItem.created_at.desc()).all()
    
    return items


# --- 2. Добавление вещи через загрузку файла ---
@router.post("/add-file", response_model=ItemResponse, summary="Загрузить вещь файлом")
async def add_item_by_file(
    name: str = Form(...), 
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    file_bytes = await file.read()
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        raise HTTPException(400, f"Ошибка изображения: {error}")

    try:
        # 1. Сохранение изображения
        image_url = save_image(file_bytes, WardrobeItem.IMAGE_SUBDIR, user_id, name)
        
        # 2. Создание записи в БД
        new_item = WardrobeItem(
            user_id=user_id,
            name=name,
            image_url=image_url,
            source_type="file_upload",
            created_at=datetime.utcnow()
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        
        return new_item
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Ошибка сервера при обработке файла: {e}")


# --- 3. Добавление вещи по URL (Ручной ввод) ---
@router.post("/add-manual-url", response_model=ItemResponse, summary="Добавить вещь по URL (ручной ввод)")
async def add_item_by_manual_url(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    # Используем run_in_executor для запуска синхронной функции в отдельном потоке
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_and_save_image(payload.url, payload.name, user_id, "url_manual", db)
    )


# --- 4. Добавление вещи по URL (Маркетплейс) ---
@router.post("/add-marketplace", response_model=ItemResponse, summary="Добавить вещь по URL (маркетплейс)")
async def add_item_by_marketplace(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    # ИСПОЛЬЗУЕМ run_in_executor для запуска синхронной функции в отдельном потоке
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_and_save_image(payload.url, payload.name, user_id, "url_marketplace", db)
    )


# --- 5. Удаление вещи ---
@router.delete("/delete", summary="Удалить вещь из гардероба")
def delete_item(
    item_id: int = Query(..., description="ID предмета гардероба"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или не принадлежит пользователю")
        
    try:
        # 1. Удаление изображения с диска
        delete_image(item.image_url) 
        
        # 2. Удаление записи из БД
        db.delete(item)
        db.commit()
        
        return {"message": f"Вещь с ID {item_id} успешно удалена"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {e}")
