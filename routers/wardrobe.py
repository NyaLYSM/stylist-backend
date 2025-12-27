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

def get_wb_image_url(nm_id: int) -> str:
    """
    Современная формула построения URL изображений Wildberries (2024-2025).
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    
    # Определяем хост на основе vol
    if vol >= 0 and vol <= 143:
        basket = "01"
    elif vol >= 144 and vol <= 287:
        basket = "02"
    elif vol >= 288 and vol <= 431:
        basket = "03"
    elif vol >= 432 and vol <= 719:
        basket = "04"
    elif vol >= 720 and vol <= 1007:
        basket = "05"
    elif vol >= 1008 and vol <= 1061:
        basket = "06"
    elif vol >= 1062 and vol <= 1115:
        basket = "07"
    elif vol >= 1116 and vol <= 1169:
        basket = "08"
    elif vol >= 1170 and vol <= 1313:
        basket = "09"
    elif vol >= 1314 and vol <= 1601:
        basket = "10"
    elif vol >= 1602 and vol <= 1655:
        basket = "11"
    elif vol >= 1656 and vol <= 1919:
        basket = "12"
    elif vol >= 1920 and vol <= 2045:
        basket = "13"
    elif vol >= 2046 and vol <= 2189:
        basket = "14"
    elif vol >= 2190 and vol <= 2405:
        basket = "15"
    elif vol >= 2406 and vol <= 2621:
        basket = "16"
    elif vol >= 2622 and vol <= 2837:
        basket = "17"
    elif vol >= 2838 and vol <= 3053:
        basket = "18"
    elif vol >= 3054 and vol <= 3269:
        basket = "19"
    elif vol >= 3270 and vol <= 3485:
        basket = "20"
    elif vol >= 3486 and vol <= 3701:
        basket = "21"
    else:
        basket = "22"
    
    host = f"basket-{basket}.wbbasket.ru"
    return f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"

def get_marketplace_data(url: str):
    """
    Парсер страниц. Для WB использует внутренний API карточек товара.
    """
    image_url = None
    title = None

    # 1. WILDBERRIES - Используем их внутренний API
    if "wildberries" in url or "wb.ru" in url:
        try:
            # Извлекаем артикул из URL
            match = re.search(r'catalog/(\d+)', url)
            if not match:
                logger.error("Could not extract article number from WB URL")
                return None, None
            
            nm_id = int(match.group(1))
            logger.info(f"WB article detected: {nm_id}")
            
            # Используем ПУБЛИЧНЫЙ API карточек WB (не требует авторизации)
            # Это официальный endpoint, который использует сам сайт WB
            vol = nm_id // 100000
            part = nm_id // 1000
            
            api_url = f"https://basket-{vol:02d}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/info/ru/card.json"
            
            logger.info(f"Fetching WB API: {api_url}")
            
            # Используем обычный requests для API (не crequests)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            response = requests.get(api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # API возвращает структуру с медиа-файлами
                if 'media' in data and 'images' in data['media']:
                    images = data['media']['images']
                    if images and len(images) > 0:
                        # Берём первое изображение в большом размере
                        first_img = images[0]
                        # Формат: https://basket-XX.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/{N}.jpg
                        image_url = f"https://basket-{vol:02d}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/{first_img}.jpg"
                
                # Название товара
                if 'imt_name' in data:
                    title = data['imt_name']
                
                logger.info(f"WB API result: image={image_url}, title={title}")
                
                if image_url:
                    return image_url, title
            else:
                logger.error(f"WB API returned status {response.status_code}")
            
            # Fallback: Если API не сработал, пробуем прямую ссылку на первое фото
            if not image_url:
                logger.info("WB API failed, trying direct image URL")
                image_url = f"https://basket-{vol:02d}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"
                title = f"Товар WB {nm_id}"
                return image_url, title
                
        except Exception as e:
            logger.error(f"WB processing failed: {e}")
            return None, None

    # 2. ОСТАЛЬНЫЕ МАРКЕТПЛЕЙСЫ (Парсинг HTML через curl_cffi)
    try:
        response = crequests.get(url, impersonate="chrome120", timeout=15, allow_redirects=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "lxml")
            
            # Ищем картинку
            og_image = soup.find("meta", property="og:image")
            if og_image:
                image_url = og_image.get("content")
            
            # Ищем название
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content")
            elif soup.title:
                title = soup.title.string
            
            if title:
                title = title.split('|')[0].split('купить')[0].strip()

    except Exception as e:
        logger.error(f"Scraper error for {url}: {e}")
    
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




