import os
import uuid
import time
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

# === ИНИЦИАЛИЗАЦИЯ LOGGER СНАЧАЛА ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ТЕПЕРЬ БЕЗОПАСНЫЙ ИМПОРТ НОВЫХ МОДУЛЕЙ ===
CLIP_AVAILABLE = False
IMAGE_PROCESSOR_AVAILABLE = False

try:
    from utils.clip_client import clip_generate_name, check_clip_service
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client module loaded")
except ImportError as e:
    logger.warning(f"⚠️ CLIP client not available: {e}")
    # Заглушки
    def clip_generate_name(image_url: str) -> dict:
        return {"success": False, "name": "Покупка"}
    def check_clip_service() -> bool:
        return False

try:
    from utils.image_processor import generate_image_variants, convert_variant_to_bytes
    IMAGE_PROCESSOR_AVAILABLE = True
    logger.info("✅ Image processor module loaded")
except ImportError as e:
    logger.warning(f"⚠️ Image processor not available: {e}")
    # Заглушки
    def generate_image_variants(img, output_size=800):
        return {"original": img}
    def convert_variant_to_bytes(img, format="JPEG", quality=85):
        output = BytesIO()
        if img.mode in ("RGBA", "P", "LA", "L"):
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode in ("RGBA", "LA"):
                rgb_img.paste(img, mask=img.split()[-1])
            else:
                rgb_img.paste(img)
            img = rgb_img
        img.save(output, format=format, quality=quality, optimize=True)
        return output.getvalue()

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

class SelectVariantPayload(BaseModel):
    temp_id: str
    selected_variant: str
    name: str

VARIANTS_STORAGE = {}
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
    Улучшенный метод поиска изображений WB с расширенной диагностикой
    """
    vol = nm_id // 100000
    part = nm_id // 1000
    
    # Расширенный список серверов (актуализировано на 2025)
    hosts = [f"basket-{i:02d}.wbbasket.ru" for i in range(1, 26)]
    
    # Добавляем альтернативные домены
    hosts.extend([
        f"basket-{i:02d}.wb.ru" for i in range(1, 13)
    ])
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    logger.info(f"🔍 Searching WB image for ID {nm_id} (vol={vol}, part={part}) on {len(hosts)} servers...")

    # Пробуем разные варианты URL
    url_templates = [
        "https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg",
        "https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.webp",
        "https://{host}/vol{vol}/part{part}/{nm_id}/images/c516x688/1.jpg",
    ]

    for template in url_templates:
        for host in hosts:
            url = template.format(host=host, vol=vol, part=part, nm_id=nm_id)
            try:
                # Увеличенный timeout для Render.com (2 сек вместо 0.5)
                resp = requests.head(url, headers=headers, timeout=2, allow_redirects=True)
                
                if resp.status_code == 200:
                    logger.info(f"✅ Image FOUND at: {host} (template: {template.split('/')[-3]})")
                    return url
                    
                # Логируем важные ошибки
                if resp.status_code in [403, 429, 498]:
                    logger.debug(f"⚠️ {host}: HTTP {resp.status_code}")
                    
            except requests.exceptions.Timeout:
                logger.debug(f"⏱️ Timeout for {host}")
                continue
            except requests.exceptions.ConnectionError:
                logger.debug(f"🔌 Connection error for {host}")
                continue
            except Exception as e:
                logger.debug(f"❗ Error for {host}: {type(e).__name__}")
                continue
    
    # Если не нашли - пробуем через API WB (запасной вариант)
    try:
        logger.info(f"🔄 Trying WB API as fallback...")
        api_url = f"https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={nm_id}"
        
        resp = requests.get(api_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data', {}).get('products'):
                product = data['data']['products'][0]
                if product.get('images'):
                    # Получаем первое изображение
                    img_data = product['images'][0]
                    if isinstance(img_data, dict) and 'big' in img_data:
                        api_image_url = img_data['big']
                    elif isinstance(img_data, str):
                        api_image_url = f"https://basket-01.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/{img_data}.jpg"
                    else:
                        api_image_url = None
                    
                    if api_image_url:
                        logger.info(f"✅ Found via API: {api_image_url}")
                        return api_image_url
    except Exception as e:
        logger.warning(f"API fallback failed: {e}")
            
    logger.warning(f"❌ Image not found on any WB server for ID {nm_id}")
    return None

def get_marketplace_data(url: str):
    """
    Возвращает: (список URL картинок, название товара)
    """
    image_urls = []
    title = None
    
    # 1. WILDBERRIES
    if "wildberries" in url or "wb.ru" in url:
        try:
            match = re.search(r'catalog/(\d+)', url)
            if not match:
                logger.error("❌ Could not extract product ID from URL")
                return [], None
                
            nm_id = int(match.group(1))
            logger.info(f"✅ Extracted product ID: {nm_id}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            api_url = f"https://card.wb.ru/cards/v1/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={nm_id}"
            logger.info(f"🔍 Fetching WB product data for ID {nm_id}...")
            
            response = requests.get(api_url, headers=headers, timeout=10)
            logger.info(f"📊 WB API response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📦 API response keys: {list(data.keys())}")
                
                if not data.get('data'):
                    logger.error("❌ No 'data' key in response")
                    return [], None
                
                if not data['data'].get('products'):
                    logger.error("❌ No 'products' in data")
                    return [], None
                
                product = data['data']['products'][0]
                logger.info(f"✅ Product data found, keys: {list(product.keys())}")
                
                # Название
                title = product.get('name', 'Товар Wildberries')
                logger.info(f"📝 Product title: {title[:50]}...")
                
                # Вычисляем vol и part
                vol = nm_id // 100000
                part = nm_id // 1000
                logger.info(f"📐 Calculated vol={vol}, part={part}")
                
                # Ищем изображения
                for img_num in range(1, 11):
                    logger.info(f"  🔍 Searching for image #{img_num}...")
                    img_url = find_wb_single_image(nm_id, vol, part, img_num)
                    if img_url:
                        image_urls.append(img_url)
                        logger.info(f"  ✅ Found image #{img_num}: {img_url[:60]}...")
                    else:
                        logger.info(f"  ⚠️ Image #{img_num} not found, stopping search")
                        break  # Останавливаемся если не нашли
                
                logger.info(f"✅ Total found {len(image_urls)} images for WB product")
                
                if image_urls:
                    return image_urls, title
                else:
                    logger.error("❌ No images found via CDN search")
                    return [], title
            else:
                logger.error(f"❌ WB API returned status {response.status_code}")
                return [], None
                
        except Exception as e:
            logger.error(f"❌ WB logic failed: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return [], None

    # 2. Другие маркетплейсы
    try:
        logger.info(f"🔍 Trying to scrape from: {url[:50]}...")
        response = crequests.get(url, impersonate="chrome120", timeout=12, allow_redirects=True)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "lxml")
            
            # Название
            og_title = soup.find("meta", property="og:title")
            if og_title: 
                title = og_title.get("content")
            elif soup.title: 
                title = soup.title.string
            
            if title: 
                title = title.split('|')[0].strip()
            
            # Основное изображение
            og_image = soup.find("meta", property="og:image")
            if og_image:
                image_urls.append(og_image.get("content"))
            
            # Дополнительные
            for img_tag in soup.find_all('img'):
                src = img_tag.get('src') or img_tag.get('data-src')
                if src and any(x in src for x in ['large', 'big', 'original', 'zoom']):
                    if src not in image_urls:
                        image_urls.append(src)
                        if len(image_urls) >= 10:
                            break
            
            logger.info(f"✅ Found {len(image_urls)} images via scraping")

    except Exception as e:
        logger.error(f"❌ Scraper error: {type(e).__name__}: {e}")
    
    logger.info(f"📊 Returning {len(image_urls)} images and title: {title[:30] if title else 'None'}...")
    return image_urls, title

def find_wb_single_image(nm_id: int, vol: int, part: int, img_num: int) -> str:
    """Ищет конкретное изображение WB"""
    hosts = [f"basket-{i:02d}.wbbasket.ru" for i in range(1, 13)]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    templates = [
        f"https://{{host}}/vol{vol}/part{part}/{nm_id}/images/big/{img_num}.jpg",
        f"https://{{host}}/vol{vol}/part{part}/{nm_id}/images/big/{img_num}.webp",
    ]
    
    for template in templates:
        for host in hosts:
            url = template.format(host=host)
            try:
                resp = requests.head(url, headers=headers, timeout=1)
                if resp.status_code == 200:
                    return url
            except:
                continue
    
    return None

def extract_smart_title(full_title: str) -> str:
    """
    Извлекает ключевые слова из названия товара
    Пример: "Брюки женские палаццо широкие летние 2024" -> "Брюки палаццо"
    """
    if not full_title:
        return "Покупка"
    
    # Убираем лишнее
    title = full_title.lower()
    
    # Убираем размеры
    title = re.sub(r'\b\d+[-/]\d+\b', '', title)  # 42-44, 42/44
    title = re.sub(r'\b[xsmlXSML]{1,3}\b', '', title)  # S, M, L, XL, XXL
    
    # Убираем годы и сезоны
    title = re.sub(r'\b20\d{2}\b', '', title)  # 2024, 2025
    title = re.sub(r'\b(весна|лето|осень|зима|сезон)\b', '', title)
    
    # Убираем стоп-слова
    stop_words = [
        'женские', 'мужские', 'детские', 'для', 'новые', 'модные',
        'стильные', 'красивые', 'качественные', 'купить', 'цена',
        'интернет', 'магазин', 'доставка', 'скидка', 'распродажа'
    ]
    
    for word in stop_words:
        title = re.sub(rf'\b{word}\b', '', title)
    
    # Чистим пробелы
    title = ' '.join(title.split())
    
    # Берем первые 2-3 значимых слова
    words = title.split()
    
    # Фильтруем короткие слова (предлоги)
    meaningful_words = [w for w in words if len(w) > 2]
    
    # Берём первые 2-3 слова
    result_words = meaningful_words[:3] if len(meaningful_words) >= 3 else meaningful_words[:2]
    
    result = ' '.join(result_words).capitalize()
    
    # Если получилось слишком коротко
    if len(result) < 3:
        # Берём первые 30 символов оригинала
        result = full_title[:30].strip()
    
    return result if result else "Покупка"

def download_direct_url(image_url: str, name: str, user_id: int, item_type: str, db: Session):
    logger.info(f"Downloading from: {image_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Referer': 'https://www.wildberries.ru/',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }

    max_retries = 3
    file_bytes = None
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.info(f"📥 Download attempt {attempt + 1}/{max_retries}")
            
            response = requests.get(
                image_url, 
                headers=headers, 
                timeout=25, 
                stream=True,
                allow_redirects=True
            )
            
            logger.info(f"📊 Response status: {response.status_code}, Content-Type: {response.headers.get('Content-Type', 'unknown')}")
            
            if response.status_code == 200:
                file_bytes = response.content
                logger.info(f"✅ Downloaded {len(file_bytes)} bytes")
                break
            
            elif response.status_code in [403, 498]:
                logger.error(f"🚫 WB blocked request: {response.status_code}")
                
                if attempt < max_retries - 1 and '.webp' in image_url:
                    image_url = image_url.replace('.webp', '.jpg')
                    logger.info(f"🔄 Trying alternative format: {image_url}")
                    time.sleep(1)
                    continue
                else:
                    raise HTTPException(
                        400, 
                        "Wildberries временно заблокировал скачивание. "
                        "Попробуйте через минуту или скопируйте прямую ссылку на фото (ПКМ → Копировать URL картинки)."
                    )
            
            elif response.status_code == 404:
                raise HTTPException(400, "Изображение не найдено на сервере")
            
            else:
                logger.warning(f"⚠️ Unexpected status: {response.status_code}")
                last_error = f"HTTP {response.status_code}"
                
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    raise HTTPException(400, f"Ошибка скачивания: код {response.status_code}")
                    
        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ Timeout on attempt {attempt + 1}")
            last_error = "Превышено время ожидания"
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                raise HTTPException(400, "Превышено время ожидания загрузки изображения")
                
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"🔌 Connection error: {e}")
            last_error = "Ошибка соединения"
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise HTTPException(400, "Ошибка соединения с сервером")
                
        except HTTPException:
            raise
            
        except Exception as e:
            logger.error(f"❌ Download exception on attempt {attempt + 1}: {type(e).__name__}: {e}")
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                raise HTTPException(400, f"Ошибка загрузки: {last_error}")

    if not file_bytes:
        raise HTTPException(400, f"Не удалось скачать изображение: {last_error}")

    # Валидация байтов
    logger.info(f"🔍 Validating image bytes...")
    valid, error = validate_image_bytes(file_bytes)
    
    if not valid:
        if b"<html" in file_bytes[:500].lower() or b"<!doctype" in file_bytes[:500].lower():
            logger.error(f"❌ Received HTML instead of image")
            raise HTTPException(
                400, 
                "Получена страница сайта вместо картинки. Защита отботов активна. "
                "Используйте прямую ссылку на фото (ПКМ по изображению → Копировать URL картинки)."
            )
        
        logger.error(f"❌ Invalid image: {error}")
        raise HTTPException(400, error)
    
    # Обработка и сохранение изображения
    try:
        logger.info(f"💾 Processing and saving image...")
        
        # Открываем изображение для проверки и конвертации
        img = Image.open(BytesIO(file_bytes))
        img_format = img.format or "JPEG"
        
        logger.info(f"📷 Original format: {img_format}, mode: {img.mode}, size: {img.size}")
        
        # Определяем нужна ли конвертация
        need_conversion = img.mode in ("RGBA", "P", "LA", "L")
        
        if need_conversion:
            logger.info(f"🎨 Converting {img.mode} to RGB")
            
            # Создаём RGB изображение с белым фоном
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            
            # Накладываем исходное изображение
            if img.mode in ("RGBA", "LA"):
                # Используем альфа-канал как маску
                rgb_img.paste(img, mask=img.split()[-1])
            else:
                rgb_img.paste(img)
            
            img = rgb_img
            
            # Конвертируем в JPEG bytes
            output = BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            final_bytes = output.getvalue()
            filename = f"market_{uuid.uuid4().hex}.jpg"
            
            logger.info(f"✅ Converted to JPEG, new size: {len(final_bytes)} bytes")
        else:
            # Если конвертация не нужна, используем оригинальные байты
            final_bytes = file_bytes
            
            # Определяем расширение
            ext = ".jpg"
            if img_format.upper() in ['JPEG', 'JPG']:
                ext = ".jpg"
            elif img_format.upper() == 'PNG':
                ext = ".png"
            elif img_format.upper() == 'WEBP':
                ext = ".webp"
            elif img_format.upper() == 'GIF':
                ext = ".gif"
            
            filename = f"market_{uuid.uuid4().hex}{ext}"
            logger.info(f"✅ Using original format: {ext}")
        
        # Закрываем PIL объект
        img.close()
        
        # Сохраняем через вашу функцию (она ожидает filename и bytes)
        final_url = save_image(filename, final_bytes)
        logger.info(f"✅ Image saved successfully: {final_url}")
        
    except Exception as e:
        logger.error(f"❌ Save error: {type(e).__name__}: {e}")
        raise HTTPException(500, f"Ошибка сохранения изображения: {str(e)}")
    
    # Сохраняем в БД
    try:
        item = WardrobeItem(
            user_id=user_id,
            name=name.strip()[:100],
            item_type=item_type,
            image_url=final_url,
            created_at=datetime.utcnow()
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info(f"✅ Item saved to DB: id={item.id}")
        return item
        
    except Exception as e:
        logger.error(f"❌ DB error: {type(e).__name__}: {e}")
        # Удаляем загруженное изображение при ошибке БД
        try:
            delete_image(final_url)
        except:
            pass
        raise HTTPException(500, f"Ошибка сохранения в базу данных: {str(e)}")

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
    
    found_image, found_title = await loop.run_in_executor(None, lambda: get_marketplace_data(payload.url))
    
    final_name = payload.name or found_title[:30] if found_title else "Покупка"

    # Более понятное сообщение об ошибке
    if not found_image:
        if "wildberries" in payload.url or "wb.ru" in payload.url:
            raise HTTPException(
                400, 
                "Не удалось найти изображение товара на Wildberries. "
                "Попробуйте: 1) Обновить страницу товара 2) Скопировать прямую ссылку на фото (ПКМ по фото → Копировать URL картинки)"
            )
        elif "ozon" in payload.url:
            raise HTTPException(400, "Не удалось получить доступ к изображению Ozon")
        else:
            # Для других сайтов пробуем качать напрямую
            pass
    
    target_url = found_image if found_image else payload.url
    return await loop.run_in_executor(None, lambda: download_direct_url(target_url, final_name, user_id, "marketplace", db))

@router.delete("/delete")
def delete_item(item_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item: raise HTTPException(404, "Not found")
    try: delete_image(item.image_url)
    except: pass
    db.delete(item); db.commit()
    return {"status": "success"}

def download_image_bytes(image_url: str) -> bytes:
    """Вспомогательная функция для скачивания bytes"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.wildberries.ru/',
    }
    
    response = requests.get(image_url, headers=headers, timeout=25, allow_redirects=True)
    
    if response.status_code != 200:
        raise HTTPException(400, f"Ошибка скачивания: код {response.status_code}")
    
    return response.content

def cleanup_old_variants():
    """Удаляет варианты старше 10 минут"""
    from datetime import timedelta
    
    now = datetime.utcnow()
    to_delete = []
    
    for temp_id, data in VARIANTS_STORAGE.items():
        age = now - data["created_at"]
        if age > timedelta(minutes=10):
            to_delete.append(temp_id)
            # Удаляем превью
            for preview_url in data.get("previews", {}).values():
                try:
                    delete_image(preview_url)
                except:
                    pass
    
    for temp_id in to_delete:
        del VARIANTS_STORAGE[temp_id]
        logger.info(f"🗑️ Cleaned up old variants: {temp_id}")

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(
    payload: ItemUrlPayload, 
    db: Session = Depends(get_db), 
    user_id: int = Depends(get_current_user_id)
):
    """
    Получает ВСЕ фотографии товара с маркетплейса
    Возвращает превью для выбора лучшего варианта
    """
    loop = asyncio.get_event_loop()
    
    # 1. Получаем все изображения и название
    logger.info(f"🔍 Fetching marketplace images...")
    image_urls, full_title = await loop.run_in_executor(
        None, 
        lambda: get_marketplace_data(payload.url)
    )
    
    if not image_urls:
        raise HTTPException(
            400, 
            "Не удалось найти изображения товара. "
            "Попробуйте скопировать прямую ссылку на фото."
        )
    
    logger.info(f"✅ Found {len(image_urls)} images")
    
    # 2. Умное извлечение названия
    if payload.name:
        suggested_name = payload.name
    elif full_title:
        suggested_name = extract_smart_title(full_title)
        logger.info(f"💡 Smart title extracted: '{suggested_name}' from '{full_title}'")
    else:
        suggested_name = "Покупка"
    
    # 3. Скачиваем и создаём превью для каждого изображения
    temp_id = uuid.uuid4().hex
    variant_previews = {}
    variant_full_urls = {}  # Храним оригинальные URL
    
    # Ограничиваем до 10 изображений
    image_urls = image_urls[:10]
    
    for idx, img_url in enumerate(image_urls):
        variant_key = f"variant_{idx + 1}"
        
        try:
            # Скачиваем изображение
            file_bytes = await loop.run_in_executor(
                None,
                lambda url=img_url: download_image_bytes(url)
            )
            
            # Валидация
            valid, error = validate_image_bytes(file_bytes)
            if not valid:
                logger.warning(f"⚠️ Image {idx+1} invalid: {error}")
                continue
            
            # Создаём превью (300x300)
            img = Image.open(BytesIO(file_bytes))
            
            # Превью
            preview_img = img.copy()
            preview_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            
            # Конвертируем в bytes
            preview_output = BytesIO()
            if preview_img.mode in ("RGBA", "P", "LA"):
                preview_rgb = Image.new("RGB", preview_img.size, (255, 255, 255))
                if preview_img.mode in ("RGBA", "LA"):
                    preview_rgb.paste(preview_img, mask=preview_img.split()[-1])
                else:
                    preview_rgb.paste(preview_img)
                preview_img = preview_rgb
            
            preview_img.save(preview_output, format='JPEG', quality=70, optimize=True)
            preview_bytes = preview_output.getvalue()
            
            # Сохраняем превью
            preview_filename = f"preview_{temp_id}_{variant_key}.jpg"
            preview_url = save_image(preview_filename, preview_bytes)
            
            variant_previews[variant_key] = preview_url
            variant_full_urls[variant_key] = img_url  # Сохраняем оригинальный URL
            
            img.close()
            
            logger.info(f"✅ Preview {idx+1} created")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to process image {idx+1}: {e}")
            continue
    
    if not variant_previews:
        raise HTTPException(400, "Не удалось обработать ни одного изображения")
    
    # 4. Сохраняем во временное хранилище
    VARIANTS_STORAGE[temp_id] = {
        "image_urls": variant_full_urls,  # Оригинальные URL для скачивания
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "previews": variant_previews,
        "source_url": payload.url
    }
    
    # Очистка старых
    cleanup_old_variants()
    
    return {
        "temp_id": temp_id,
        "suggested_name": suggested_name,
        "variants": variant_previews,
        "total_images": len(variant_previews),
        "message": "Выберите лучшее фото товара"
    }

@router.post("/select-variant", response_model=ItemResponse)
async def select_and_save_variant(
    payload: SelectVariantPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Пользователь выбрал фото - скачиваем оригинал и сохраняем
    """
    if payload.temp_id not in VARIANTS_STORAGE:
        raise HTTPException(404, "Варианты не найдены или истекло время")
    
    stored = VARIANTS_STORAGE[payload.temp_id]
    
    if stored["user_id"] != user_id:
        raise HTTPException(403, "Нет доступа")
    
    selected_variant = payload.selected_variant
    if selected_variant not in stored["image_urls"]:
        raise HTTPException(400, f"Неизвестный вариант: {selected_variant}")
    
    logger.info(f"💾 User selected: {selected_variant}")
    
    # Получаем оригинальный URL выбранного изображения
    selected_image_url = stored["image_urls"][selected_variant]
    
    # Скачиваем оригинал в полном размере
    loop = asyncio.get_event_loop()
    
    try:
        file_bytes = await loop.run_in_executor(
            None,
            lambda: download_image_bytes(selected_image_url)
        )
        
        # Валидация
        valid, error = validate_image_bytes(file_bytes)
        if not valid:
            raise HTTPException(400, error)
        
        # Обрабатываем и сохраняем
        img = Image.open(BytesIO(file_bytes))
        img_format = img.format or "JPEG"
        
        # Конвертация если нужна
        need_conversion = img.mode in ("RGBA", "P", "LA", "L")
        
        if need_conversion:
            rgb_img = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode in ("RGBA", "LA"):
                rgb_img.paste(img, mask=img.split()[-1])
            else:
                rgb_img.paste(img)
            img = rgb_img
            
            output = BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            final_bytes = output.getvalue()
            filename = f"wardrobe_{uuid.uuid4().hex}.jpg"
        else:
            final_bytes = file_bytes
            ext = ".jpg"
            if img_format.upper() in ['JPEG', 'JPG']:
                ext = ".jpg"
            elif img_format.upper() == 'PNG':
                ext = ".png"
            elif img_format.upper() == 'WEBP':
                ext = ".webp"
            
            filename = f"wardrobe_{uuid.uuid4().hex}{ext}"
        
        img.close()
        
        # Сохраняем
        final_url = save_image(filename, final_bytes)
        logger.info(f"✅ Saved selected image: {final_url}")
        
    except Exception as e:
        logger.error(f"❌ Error saving selected image: {e}")
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")
    
    # Удаляем все превью
    for preview_url in stored["previews"].values():
        try:
            delete_image(preview_url)
        except:
            pass
    
    # Удаляем из хранилища
    del VARIANTS_STORAGE[payload.temp_id]
    
    # Сохраняем в БД
    item = WardrobeItem(
        user_id=user_id,
        name=payload.name.strip()[:100],
        item_type="marketplace",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    
    logger.info(f"✅ Item saved: id={item.id}")
    
    return item




