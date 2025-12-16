# routers/wardrobe.py (Полный исправленный файл с отладочными сообщениями)

import os
import requests 
from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from pydantic import BaseModel 
from sqlalchemy.orm import Session
from io import BytesIO 
from PIL import Image 

# Абсолютные импорты (убедитесь, что они существуют)
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from utils.validators import validate_name
from utils.auth import get_current_user_id # Предполагается, что эта зависимость существует

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

# Вспомогательная функция для загрузки URL 
def download_and_save_image(url: str, name: str, user_id: int, item_type: str, db: Session):
    print(f"DEBUG: Download (URL) - Starting for {name} from {url}") # <<< ОТЛАДКА 1
    
    try:
        # Установка таймаута для предотвращения зависания
        response = requests.get(url, timeout=15) # Увеличен таймаут на 5 сек
        response.raise_for_status() # Вызывает исключение для 4xx/5xx
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Download failed: {e}") # <<< ОТЛАДКА 1.1
        raise HTTPException(400, f"Ошибка скачивания фото по URL: {str(e)}")
        
    file_bytes = response.content
    
    print(f"DEBUG: Download (URL) - Image downloaded. Starting validation.") # <<< ОТЛАДКА 2
    
    valid_image, image_error = validate_image_bytes(file_bytes) 
    if not valid_image:
        print(f"DEBUG: Validation failed: {image_error}") # <<< ОТЛАДКА 2.1
        raise HTTPException(400, f"Ошибка файла: {image_error}")

    # Сохранение
    try:
        filename = url.split('/')[-1].split('?')[0] or f"item_{user_id}_{name[:10]}.jpg"
        print(f"DEBUG: Download (URL) - Starting save_image for {filename}.") # <<< ОТЛАДКА 3
        final_url = save_image(filename, file_bytes)
    except Exception as e:
        print(f"DEBUG: Save failed: {e}") # <<< ОТЛАДКА 3.1
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
    
    print(f"DEBUG: Download (URL) - Item {item.id} saved successfully. Returning response.") # <<< ОТЛАДКА 4
    
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
    print(f"DEBUG: Upload (File) - Starting for {name}") # <<< ОТЛАДКА 5
    
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")

    file_bytes = await image.read()
    
    print(f"DEBUG: Upload (File) - File read. Starting validation.") # <<< ОТЛАДКА 6
    
    valid_image, image_error = validate_image_bytes(file_bytes)
    if not valid_image:
        raise HTTPException(400, f"Ошибка файла: {image_error}")

    try:
        print(f"DEBUG: Upload (File) - Starting save_image for {image.filename}.") # <<< ОТЛАДКА 7
        final_url = save_image(image.filename, file_bytes)
    except Exception as e:
        print(f"DEBUG: Save failed: {e}") # <<< ОТЛАДКА 7.1
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
    
    print(f"DEBUG: Upload (File) - Item {item.id} saved successfully. Returning response.") # <<< ОТЛАДКА 8

    return {"status": "success", "item_id": item.id, "image_url": final_url}

# --- 3. Добавление вещи по URL (Ручной режим) ---
@router.post("/add-url")
def add_item_by_url(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    return download_and_save_image(payload.url, payload.name, user_id, "url_manual", db)


# --- 4. Добавление вещи по URL (Маркетплейс) ---
@router.post("/add-marketplace")
def add_item_by_marketplace(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    valid_name, name_error = validate_name(payload.name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")
        
    return download_and_save_image(payload.url, payload.name, user_id, "url_marketplace", db)


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
