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

def download_and_save_image_sync(url: str, name: str, user_id: int, item_type: str, db: Session):
    """
    Скачивание изображения с URL и сохранение в БД.
    Поддерживает маркетплейсы (WB, Ozon и др.)
    """
    
    # Проверка: это прямая ссылка на изображение или страница товара
    is_direct_image = any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'])
    
    # Заголовки для имитации браузера (обход блокировок)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'image',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'cross-site',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    
    # Определяем Referer по домену
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc
    
    if 'wildberries' in domain or 'wb.ru' in domain:
        headers['Referer'] = 'https://www.wildberries.ru/'
    elif 'ozon' in domain:
        headers['Referer'] = 'https://www.ozon.ru/'
    elif 'aliexpress' in domain:
        headers['Referer'] = 'https://www.aliexpress.ru/'
    elif 'lamoda' in domain:
        headers['Referer'] = 'https://www.lamoda.ru/'
    else:
        headers['Referer'] = f'https://{domain}/'
    
    # Скачивание с retry логикой
    max_retries = 3
    last_error = None
    file_bytes = None  # ✅ ИНИЦИАЛИЗИРУЕМ
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, 
                headers=headers,
                timeout=15,
                allow_redirects=True,
                stream=True  # Для больших файлов
            )
            response.raise_for_status()
            
            # Успешно скачали
            file_bytes = response.content
            break
            
        except requests.exceptions.HTTPError as e:
            last_error = e
            status_code = e.response.status_code if e.response else 0
            
            # Специальная обработка для разных кодов
            if status_code == 403:
                # Forbidden - пробуем без некоторых заголовков
                headers.pop('Sec-Fetch-Dest', None)
                headers.pop('Sec-Fetch-Mode', None)
                headers.pop('Sec-Fetch-Site', None)
            elif status_code == 498:
                # Token expired/invalid - пробуем упрощенные заголовки
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': headers.get('Referer', '')
                }
            elif status_code >= 500:
                # Ошибка сервера - ждем и повторяем
                import time
                time.sleep(1)
            else:
                # Другие ошибки - не повторяем
                break
                
        except requests.exceptions.Timeout:
            last_error = Exception("Timeout: сервер не отвечает")
            import time
            time.sleep(1)
            
        except requests.exceptions.RequestException as e:
            last_error = e
            break
    else:
        # Все попытки исчерпаны
        error_msg = str(last_error) if last_error else "Неизвестная ошибка"
        raise HTTPException(400, f"Не удалось скачать фото после {max_retries} попыток: {error_msg}")
    
    # ✅ ПРОВЕРКА: если file_bytes так и остался None
    if file_bytes is None:
        raise HTTPException(400, "Не удалось получить данные изображения")
    
    # Валидация скачанного файла
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        raise HTTPException(400, f"Ошибка валидации файла: {error}")
    
    # Сохранение на диск/S3
    try:
        filename = f"url_{user_id}_{int(datetime.now().timestamp())}.jpg"
        final_url = save_image(filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения на диск: {str(e)}")
    
    # Создание записи в БД
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
















