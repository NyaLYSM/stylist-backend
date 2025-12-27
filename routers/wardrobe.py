import os
import uuid
import asyncio
import re
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image

# requests - для скачивания картинок (стабильно)
import requests
# curl_cffi - для парсинга страниц Ozon/Lamoda (обход защиты)
from curl_cffi import requests as crequests
from bs4 import BeautifulSoup

from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Импорты из вашего проекта
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from utils.validators import validate_name
from .dependencies import get_current_user_id

# Настройка логгера для отладки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wardrobe"])

# --- Pydantic Models ---
class ItemUrlPayload(BaseModel):
    name: str
    url: str

class ItemResponse(BaseModel):
    id: int
    name: str
    image_url: str
    item_type: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# --- Helpers ---
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

def get_marketplace_data(url: str):
    """
    Парсер страниц маркетплейсов.
    """
    image_url = None
    title = None

    # 1. WILDBERRIES - Прямая ссылка на изображение без парсинга
    if "wildberries" in url or "wb.ru" in url:
        try:
            # Извлекаем артикул
            match = re.search(r'catalog/(\d+)', url)
            if not match:
                logger.error("Could not extract article number from WB URL")
                return None, None
            
            nm_id = int(match.group(1))
            logger.info(f"WB article detected: {nm_id}")
            
            # Wildberries в 2024-2025 использует CDN images.wbstatic.net
            # Структура: https://images.wbstatic.net/{размер}/new/{part}0000/{nm_id}-1.jpg
            part = nm_id // 1000
            
            # Пробуем несколько форматов URL (WB иногда меняет структуру)
            possible_urls = [
                f"https://images.wbstatic.net/big/new/{part}0000/{nm_id}-1.jpg",
                f"https://images.wbstatic.net/c516x688/new/{part}0000/{nm_id}-1.jpg",
               f"https://images.wbstatic.net/tm/new/{part}0000/{nm_id}-1.jpg"
            ]
            
            # Берём первый URL (большой размер)
            image_url = possible_urls[0]
            title = f"Товар Wildberries {nm_id}"
            
            logger.info(f"WB direct link: {image_url}")
            return image_url, title
                
        except Exception as e:
            logger.error(f"WB processing failed: {e}")
            return None, None

    # 2. ОСТАЛЬНЫЕ МАРКЕТПЛЕЙСЫ - Парсинг HTML
    try:
        logger.info(f"Parsing URL: {url}")
        response = crequests.get(url, impersonate="chrome120", timeout=15, allow_redirects=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "lxml")
            
            # Картинка через OpenGraph
            og_image = soup.find("meta", property="og:image")
            if og_image:
                image_url = og_image.get("content")
                logger.info(f"Found og:image: {image_url}")
            
            # Название товара
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content")
            elif soup.title:
                title = soup.title.string
            
            if title:
                title = title.split('|')[0].split('купить')[0].strip()
            
            logger.info(f"Parsing result: image={image_url}, title={title}")
        else:
            logger.error(f"Page returned status {response.status_code}")

    except Exception as e:
        logger.error(f"Parsing error for {url}: {e}")
    
    return image_url, title
    
def download_direct_url(image_url: str, name: str, user_id: int, item_type: str, db: Session):
    """
    Скачивание КАРТИНКИ. Используем обычный requests, так как curl_cffi иногда сбоит на бинарных файлах в контейнерах.
    """
    logger.info(f"Downloading image from: {image_url}")
    
    # Заголовки, чтобы сервера картинок не блокировали (Referer часто нужен)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': image_url # Часто помогает при 403
    }

    try:
        # Используем requests (не crequests) для надежности с файлами
        response = requests.get(image_url, headers=headers, timeout=20, stream=True)
        
        if response.status_code != 200:
            logger.error(f"Download failed with status {response.status_code}")
            raise HTTPException(400, f"Ошибка скачивания файла: код {response.status_code}")
            
        file_bytes = response.content
        
    except Exception as e:
        logger.error(f"Download exception: {e}")
        raise HTTPException(400, f"Не удалось скачать фото: {str(e)}")

    # Валидация
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        # Если вернулся HTML (текст) вместо картинки
        if b"<html" in file_bytes[:500].lower():
             logger.error("Server returned HTML instead of image")
             raise HTTPException(400, "По ссылке находится страница, а не картинка. Попробуйте прямую ссылку на фото.")
        
        logger.error(f"Validation error: {error}")
        raise HTTPException(400, error)
    
    # Сохранение
    try:
        ext = ".jpg"
        try:
            img_head = Image.open(BytesIO(file_bytes))
            ext = f".{img_head.format.lower()}"
        except: pass

        filename = f"market_{uuid.uuid4().hex}{ext}"
        img = Image.open(BytesIO(file_bytes))
        
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            filename = filename.replace(".png", ".jpg").replace(".webp", ".jpg")
            
        final_url = save_image(img, filename)
        
    except Exception as e:
        logger.error(f"Save error: {e}")
        raise HTTPException(500, f"Ошибка сохранения: {e}")
    
    # БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type=item_type,
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item); db.commit(); db.refresh(item)
    return item

# --- Routes ---

@router.get("/items", response_model=list[ItemResponse]) 
def get_wardrobe_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.created_at.desc()).all()
    return items if items else []

@router.post("/add-file", response_model=ItemResponse)
async def add_item_file(name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    valid_name, name_error = validate_name(name)
    if not valid_name: raise HTTPException(400, name_error)

    file_bytes = await file.read()
    valid, error = validate_image_bytes(file_bytes)
    if not valid: raise HTTPException(400, error)

    try:
        filename = f"upload_{uuid.uuid4().hex}.jpg"
        img = Image.open(BytesIO(file_bytes))
        if img.mode != 'RGB': img = img.convert('RGB')
        final_url = save_image(img, filename)
    except Exception as e:
        raise HTTPException(500, str(e))

    item = WardrobeItem(user_id=user_id, name=name, item_type="file", image_url=final_url, created_at=datetime.utcnow())
    db.add(item); db.commit(); db.refresh(item)
    return item

@router.post("/add-manual-url", response_model=ItemResponse)
async def add_item_by_manual_url(payload: ItemUrlPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: download_direct_url(payload.url, payload.name, user_id, "url_manual", db))

@router.post("/add-marketplace", response_model=ItemResponse)
async def add_item_by_marketplace(payload: ItemUrlPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    loop = asyncio.get_event_loop()

    # 1. Поиск ссылки (через curl_cffi или математику)
    found_image, found_title = await loop.run_in_executor(None, lambda: get_marketplace_data(payload.url))

    final_name = payload.name
    if not final_name and found_title: final_name = found_title[:30]
    if not final_name: final_name = "Покупка"

    target_url = found_image if found_image else payload.url
    if not target_url: raise HTTPException(400, "Не удалось найти картинку.")

    # 2. Скачивание (через requests)
    return await loop.run_in_executor(None, lambda: download_direct_url(target_url, final_name, user_id, "marketplace", db))

@router.delete("/delete")
def delete_item(item_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item: raise HTTPException(404, "Not found")
    try: delete_image(item.image_url)
    except: pass
    db.delete(item); db.commit()
    return {"status": "success"}








