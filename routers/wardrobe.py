import os
import uuid
import asyncio
import re
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image

# requests - для проверки доступности и скачивания
import requests
# curl_cffi - для парсинга страниц Ozon/Lamoda
from curl_cffi import requests as crequests
from bs4 import BeautifulSoup

from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from utils.validators import validate_name
from .dependencies import get_current_user_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Wardrobe"])

# --- Models ---
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
        return False, f"Размер файла > {MAX_SIZE_MB} МБ."
    try:
        img = Image.open(BytesIO(file_bytes))
        img.verify()
        if img.format not in ['JPEG', 'PNG', 'GIF', 'WEBP']:
             return False, "Неверный формат фото."
    except Exception:
        return False, "Файл не является фото."
    return True, None

def find_wb_image_url(nm_id: int) -> str:
    """
    Метод 'Перебора': Ищет, на каком из серверов WB лежит картинка.
    Проверяет basket-01 ... basket-25.
    Это обходит ошибку 498, так как мы не трогаем основной сайт.
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    
    # Расширенный список серверов (актуален на 2025)
    hosts = [f"basket-{i:02d}.wbbasket.ru" for i in range(1, 26)]
    
    # Заголовки (минимальные, чтобы CDN не ругался)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    logger.info(f"🔍 Searching WB image for ID {nm_id} on {len(hosts)} servers...")

    # Быстрая проверка заголовков (HEAD запрос)
    for host in hosts:
        url = f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"
        try:
            # timeout=0.5 - очень быстро проверяем, есть ли файл
            resp = requests.head(url, headers=headers, timeout=0.5)
            if resp.status_code == 200:
                logger.info(f"✅ Image FOUND at: {host}")
                return url
        except:
            continue
            
    logger.warning(f"❌ Image not found on any WB server for ID {nm_id}")
    return None

def get_marketplace_data(url: str):
    image_url = None
    title = None
    
    # 1. WILDBERRIES (Спец. логика: Игнорируем сайт, ищем сразу на CDN)
    if "wildberries" in url or "wb.ru" in url:
        try:
            # Ищем ID товара в ссылке
            match = re.search(r'catalog/(\d+)', url)
            if match:
                nm_id = int(match.group(1))
                # Запускаем перебор серверов
                image_url = find_wb_image_url(nm_id)
                title = "Wildberries Item"
                if image_url:
                    return image_url, title
        except Exception as e:
            logger.error(f"WB Search logic failed: {e}")

    # 2. ОСТАЛЬНЫЕ (Ozon, Lamoda - честный парсинг через curl_cffi)
    try:
        # impersonate="chrome120" — притворяемся браузером
        response = crequests.get(url, impersonate="chrome120", timeout=12, allow_redirects=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "lxml")
            
            og_image = soup.find("meta", property="og:image")
            if og_image: 
                image_url = og_image.get("content")
                logger.info(f"Found og:image: {image_url}")

            og_title = soup.find("meta", property="og:title")
            if og_title: title = og_title.get("content")
            elif soup.title: title = soup.title.string
            
            if title: title = title.split('|')[0].strip()

    except Exception as e:
        logger.warning(f"Scraper error: {e}")
    
    return image_url, title

def download_direct_url(image_url: str, name: str, user_id: int, item_type: str, db: Session):
    logger.info(f"Downloading from: {image_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # Скачиваем файл
        response = requests.get(image_url, headers=headers, timeout=20, stream=True)
        
        if response.status_code != 200:
            logger.error(f"Download failed: {response.status_code}")
            
            # Специфичная ошибка WB (если ссылка протухла или защита CDN)
            if response.status_code in [403, 498] and "wbbasket" in image_url:
                 raise HTTPException(400, "Wildberries временно заблокировал скачивание картинки. Попробуйте вручную скопировать URL картинки.")
                 
            raise HTTPException(400, f"Ошибка скачивания: код {response.status_code}")
            
        file_bytes = response.content
        
    except Exception as e:
        logger.error(f"Download exception: {e}")
        raise HTTPException(400, f"Ошибка соединения: {str(e)}")

    # Валидация байтов (чтобы не сохранять HTML ошибки как картинки)
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        # Если скачали HTML (страницу с ошибкой)
        if b"<html" in file_bytes[:500].lower():
             raise HTTPException(400, "Получена страница сайта вместо картинки. Защита от ботов активна.")
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
    except Exception as e: raise HTTPException(500, str(e))
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
    
    # 1. Поиск ссылки (При WB запускается перебор серверов)
    found_image, found_title = await loop.run_in_executor(None, lambda: get_marketplace_data(payload.url))
    
    final_name = payload.name
    if not final_name and found_title: final_name = found_title[:30]
    if not final_name: final_name = "Покупка"

    # Если мы не нашли картинку, но ссылка похожа на маркетплейс — падаем с ошибкой,
    # чтобы не пытаться качать HTML страницу товара (что и вызывало 400/498)
    if not found_image and ("wildberries" in payload.url or "ozon" in payload.url):
        raise HTTPException(400, "Не удалось получить доступ к картинке. Сайт защищен от ботов. Пожалуйста, используйте прямую ссылку на фото (ПКМ -> Копировать URL картинки).")

    # Если скрапер не нашел, но это НЕ маркетплейс (просто ссылка на фото), пробуем качать
    target_url = found_image if found_image else payload.url

    # 2. Скачивание
    return await loop.run_in_executor(None, lambda: download_direct_url(target_url, final_name, user_id, "marketplace", db))

@router.delete("/delete")
def delete_item(item_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item: raise HTTPException(404, "Not found")
    try: delete_image(item.image_url)
    except: pass
    db.delete(item); db.commit()
    return {"status": "success"}
