# routers/wardrobe.py (Полный исправленный файл, V2)

import os
import requests 
from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from pydantic import BaseModel 
from sqlalchemy.orm import Session
from io import BytesIO 
from PIL import Image 
import asyncio 

# Абсолютные импорты
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from utils.validators import validate_name

# *** КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1: ИМПОРТ get_current_user_id ***
# ВАЖНО: Если ваш файл авторизации называется не 'auth.py', 
# замените '.auth' на правильное имя файла (например, '.tg_auth')
from .auth import get_current_user_id 


# Схема для принятия URL и имени
class ItemUrlPayload(BaseModel):
    name: str
    url: str

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
    except Exception:
        return False, "Файл не является действительным изображением."
        
    return True, None


router = APIRouter(tags=["Wardrobe"])

# Вспомогательная функция для загрузки URL (синхронная)
def download_and_save_image(url: str, name: str, user_id: int, item_type: str, db: Session):
    try:
        # Установка таймаута для предотвращения зависания
        response = requests.get(url, timeout=10) 
        response.raise_for_status() # Вызывает исключение для 4xx/5xx
    except requests.exceptions.RequestException as e:
        raise HTTPException(400, f"Ошибка скачивания фото по URL: {str(e)}")
        
    file_bytes = response.content
    
    # Используем локальную validate_image_bytes, если не импортирована
    valid_image, image_error = validate_image_bytes(file_bytes) 
    if not valid_image:
        raise HTTPException(400, f"Ошибка файла: {image_error}")

    # Сохранение
    try:
        # Придумываем имя файла
        filename = url.split('/')[-1].split('?')[0] or f"item_{user_id}_{name[:10]}.jpg"
        final_url = save_image(filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    # Запись в БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type=item_type,
        image_url=final_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    
    return {"status": "success", "item_id": item.id, "image_url": final_url}


# --- 1. Список вещей ---
@router.get("/list")
def get_all_items(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) 
):
    items = db.query(WardrobeItem).filter(
        WardrobeItem.user_id == user_id
    ).order_by(WardrobeItem.id.desc()).all()
    return {"items": items}

# --- 2. Загрузка вещи (файл) ---
@router.post("/upload")
async def add_item_file( 
    name: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")

    # Чтение файла асинхронно
    file_bytes = await image.read()
    valid_image, image_error = validate_image_bytes(file_bytes)
    if not valid_image:
        raise HTTPException(400, f"Ошибка файла: {image_error}")

    try:
        final_url = save_image(image.filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type="upload",
        image_url=final_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "success", "item_id": item.id, "image_url": final_url}

# --- 3. Добавление вещи по URL (Ручной режим) ---
@router.post("/add-url")
async def add_item_by_url( # АСИНХРОННЫЙ
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
        lambda: download_and_save_image(payload.url, payload.name, user_id, "url_manual", db)
    )


# --- 4. Добавление вещи по URL (Маркетплейс) ---
@router.post("/add-marketplace")
async def add_item_by_marketplace( # АСИНХРОННЫЙ
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        # *** КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2: ОПЕЧАТКА name:error -> name_error ***
        raise HTTPException(400, f"Ошибка названия: {name_error}") 
        
    # ИСПОЛЬЗУЕМ run_in_executor для запуска синхронной функции в отдельном потоке
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_and_save_image(payload.url, payload.name, user_id, "url_marketplace", db)
    )


# --- 5. Удаление вещи ---
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
        raise HTTPException(404, "Вещь не найдена")

    delete_image(item.image_url)
    db.delete(item)
    db.commit()

    return {"status": "success", "message": "Deleted"}
