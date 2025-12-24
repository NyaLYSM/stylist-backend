# routers/wardrobe.py

import os
import uuid
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
    item_type: str  # ✅ ИСПРАВЛЕНО: было source_type
    created_at: datetime 
    
    class Config:
        from_attributes = True

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def validate_image_bytes(file_bytes: bytes):
    MAX_SIZE_MB = 3
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


# routers/wardrobe.py - ИСПРАВЛЕННАЯ ФУНКЦИЯ

def get_basket_host(vol: int) -> str:
    """
    Математическая карта серверов Wildberries (актуальна на 2025).
    Определяет хост по номеру volume.
    """
    if 0 <= vol <= 143: return "basket-01.wbbasket.ru"
    if 144 <= vol <= 287: return "basket-02.wbbasket.ru"
    if 288 <= vol <= 431: return "basket-03.wbbasket.ru"
    if 432 <= vol <= 719: return "basket-04.wbbasket.ru"
    if 720 <= vol <= 1007: return "basket-05.wbbasket.ru"
    if 1008 <= vol <= 1061: return "basket-06.wbbasket.ru"
    if 1062 <= vol <= 1115: return "basket-07.wbbasket.ru"
    if 1116 <= vol <= 1169: return "basket-08.wbbasket.ru"
    if 1170 <= vol <= 1313: return "basket-09.wbbasket.ru"
    if 1314 <= vol <= 1601: return "basket-10.wbbasket.ru"
    if 1602 <= vol <= 1655: return "basket-11.wbbasket.ru"
    if 1656 <= vol <= 1919: return "basket-12.wbbasket.ru"
    if 1920 <= vol <= 2045: return "basket-13.wbbasket.ru"
    if 2046 <= vol <= 2189: return "basket-14.wbbasket.ru"
    if 2190 <= vol <= 2405: return "basket-15.wbbasket.ru"
    if 2406 <= vol <= 2621: return "basket-16.wbbasket.ru"
    if 2622 <= vol <= 2837: return "basket-17.wbbasket.ru"
    if 2838 <= vol <= 3053: return "basket-18.wbbasket.ru"
    if 3054 <= vol <= 3269: return "basket-19.wbbasket.ru"
    if 3270 <= vol <= 3485: return "basket-20.wbbasket.ru"
    if 3486 <= vol <= 3701: return "basket-21.wbbasket.ru"
    return "basket-22.wbbasket.ru" # Для совсем новых товаров

def resolve_wb_url(url: str) -> str:
    """
    Превращает ссылку на товар WB в точную ссылку на фото без лишних запросов.
    """
    import re
    # Ищем ID товара
    match = re.search(r'catalog/(\d+)', url)
    if not match:
        return url 

    nm_id = int(match.group(1))
    vol = nm_id // 100000
    part = nm_id // 1000
    host = get_basket_host(vol)
    
    # Формируем прямую ссылку
    return f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"

def download_and_save_image_sync(url: str, name: str, user_id: int, item_type: str, db: Session):
    
    # 1. Если это WB, вычисляем ссылку математически
    if "wildberries" in url or "wb.ru" in url:
        try:
            url = resolve_wb_url(url)
            print(f"WB Resolved: {url}") # Лог для отладки
        except Exception as e:
            print(f"WB Resolve Error: {e}")

    # Заголовки (Chrome)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    file_bytes = None
    last_error = None
    
    # 2. Скачивание
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        file_bytes = response.content
    except Exception as e:
        last_error = e

    # 3. Проверка
    if file_bytes is None:
        raise HTTPException(
            status_code=400, 
            detail=f"Не удалось скачать фото. Попробуйте вставить ПРЯМУЮ ссылку на картинку (ПКМ -> Копировать URL картинки). Ошибка: {str(last_error)}"
        )

    # Валидация
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        # Если скачался HTML (страница), значит ссылка не прямая и парсер не сработал
        if b"<html" in file_bytes[:200].lower():
             raise HTTPException(
                status_code=400, 
                detail="Это ссылка на страницу, а не на фото. Скопируйте URL самой картинки (ПКМ по фото -> Копировать URL картинки)."
            )
        raise HTTPException(400, detail=f"Файл поврежден: {error}")
    
    # 4. Сохранение
    try:
        import uuid
        filename = f"market_{uuid.uuid4().hex}.jpg"
        img = Image.open(BytesIO(file_bytes))
        
        # Если ваша save_image принимает Image объект:
        final_url = save_image(img, filename)
        # Если save_image принимает байты, используйте: save_image(filename, file_bytes)
        
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка сохранения: {str(e)}")
    
    # 5. БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type=item_type,
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
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")

    # Читаем файл
    file_bytes = await file.read()
    await file.close()
    
    # Валидация
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        raise HTTPException(400, f"Ошибка файла: {error}")

    # Сохранение
    try:
        final_url = save_image(file.filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    # Создание записи в БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type="file",  # ✅ ИСПРАВЛЕНО
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

















