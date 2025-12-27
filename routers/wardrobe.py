import os
import uuid
import asyncio
import re
import logging
from datetime import datetime
from io import BytesIO
from PIL import Image

# ВАЖНО: Используем curl_cffi вместо requests для обхода защиты (498/403 ошибок)
# Если у вас нет этой библиотеки, добавьте в requirements.txt: curl_cffi
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

# Настройка логгера
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

# --- Helper: Валидация байтов картинки ---
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

# --- Helper: Математика серверов Wildberries ---
def get_wb_host(vol: int) -> str:
    """Возвращает хост сервера WB в зависимости от ID товара."""
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
    return "basket-22.wbbasket.ru"

# --- Helper: Получение данных с маркетплейса ---
def get_marketplace_data(url: str):
    """
    Пытается найти прямую ссылку на фото и название товара.
    Использует curl_cffi для имитации браузера Chrome.
    """
    image_url = None
    title = None

    # 1. WILDBERRIES (Быстрый путь через математику)
    if "wildberries" in url or "wb.ru" in url:
        try:
            match = re.search(r'catalog/(\d+)', url)
            if match:
                nm_id = int(match.group(1))
                vol = nm_id // 100000
                part = nm_id // 1000
                host = get_wb_host(vol)
                image_url = f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"
                title = "Wildberries Item" # Название уточним позже или оставим дефолтное
                return image_url, title
        except Exception as e:
            logger.error(f"WB Math failed: {e}")

    # 2. УНИВЕРСАЛЬНЫЙ ПАРСЕР (Для Ozon, Lamoda, или если WB Math не сработал)
    try:
        # impersonate="chrome120" — ключевой момент для обхода 403/498 ошибок
        response = crequests.get(
            url, 
            impersonate="chrome120", 
            timeout=15,
            allow_redirects=True
        )
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "lxml")

            # Ищем картинку (OG Tag - стандарт для всех магазинов)
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = og_image["content"]

            # Ищем название
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"]
            elif soup.title:
                title = soup.title.string
            
            # Чистим название от мусора
            if title:
                title = title.split('|')[0].split('купить')[0].strip()

    except Exception as e:
        logger.error(f"Scraper error for {url}: {e}")
    
    return image_url, title

# --- Helper: Загрузка прямой ссылки ---
def download_direct_url(image_url: str, name: str, user_id: int, item_type: str, db: Session):
    """
    Скачивает картинку по прямой ссылке, сохраняет на диск и пишет в БД.
    """
    logger.info(f"Downloading: {image_url}")
    
    # Скачиваем через curl_cffi, так как сервера картинок тоже могут иметь защиту
    try:
        response = crequests.get(
            image_url, 
            impersonate="chrome120", 
            timeout=20
        )
        if response.status_code != 200:
            raise HTTPException(400, f"Ошибка скачивания ({response.status_code}). Ссылка недоступна.")
            
        file_bytes = response.content
        
    except Exception as e:
        raise HTTPException(400, f"Не удалось скачать фото: {str(e)}")

    # Валидация контента
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        # Проверка, не вернул ли сервер HTML страницу вместо картинки (ошибка парсера)
        if b"<html" in file_bytes[:500].lower():
             raise HTTPException(400, "Сервер вернул страницу сайта вместо картинки. Попробуйте прямую ссылку на фото.")
        raise HTTPException(400, error)
    
    # Сохранение на диск
    try:
        ext = ".jpg" # По умолчанию
        # Пытаемся определить формат
        try:
            img_head = Image.open(BytesIO(file_bytes))
            ext = f".{img_head.format.lower()}"
        except:
            pass

        filename = f"market_{uuid.uuid4().hex}{ext}"
        
        # Конвертация в PIL Image для вашей функции save_image
        img = Image.open(BytesIO(file_bytes))
        
        # Приводим к RGB, если это PNG/WEBP с прозрачностью
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            filename = filename.replace(".png", ".jpg").replace(".webp", ".jpg")
        
        # Используем вашу функцию save_image из utils.storage
        final_url = save_image(img, filename)
        
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения на сервере: {e}")
    
    # Запись в БД
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


# ==========================
# ROUTES
# ==========================

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
    # Валидация имени
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, name_error)

    # Читаем файл
    file_bytes = await file.read()
    await file.close()
    
    # Валидация файла
    valid, error = validate_image_bytes(file_bytes)
    if not valid:
        raise HTTPException(400, error)

    # Сохранение
    try:
        # Генерируем уникальное имя
        import uuid
        ext = os.path.splitext(file.filename)[1]
        if not ext: ext = ".jpg"
        filename = f"upload_{uuid.uuid4().hex}{ext}"

        img = Image.open(BytesIO(file_bytes))
        # Конвертируем если нужно
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            filename = filename.rsplit('.', 1)[0] + ".jpg"

        final_url = save_image(img, filename)

    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    # БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type="file",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.post("/add-manual-url", response_model=ItemResponse)
async def add_item_by_manual_url(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    # Этот метод используется, когда юзер вводит ПРЯМУЮ ссылку на картинку
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: download_direct_url(payload.url, payload.name, user_id, "url_manual", db)
    )

@router.post("/add-marketplace", response_model=ItemResponse)
async def add_item_by_marketplace(
    payload: ItemUrlPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    loop = asyncio.get_event_loop()

    # 1. ПАРСИНГ: Пытаемся найти картинку на странице магазина
    # Запускаем в отдельном потоке, чтобы не блокировать сервер
    found_image, found_title = await loop.run_in_executor(
        None, 
        lambda: get_marketplace_data(payload.url)
    )

    # 2. Определение названия
    final_name = payload.name
    if not final_name and found_title:
        final_name = found_title[:30] # Обрезаем длинные названия
    if not final_name:
        final_name = "Покупка"

    # 3. Выбор ссылки для скачивания
    # Если парсер нашел картинку - берем её. Если нет - берем исходный URL (на случай если это прямая ссылка)
    target_url = found_image if found_image else payload.url
    
    if not target_url:
         raise HTTPException(400, "Не удалось найти изображение по этой ссылке.")

    # 4. СКАЧИВАНИЕ
    return await loop.run_in_executor(
        None, 
        lambda: download_direct_url(target_url, final_name, user_id, "marketplace", db)
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
        pass # Не страшно, если файла уже нет

    db.delete(item)
    db.commit()
    return {"status": "success"}
