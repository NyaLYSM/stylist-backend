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

# === БЕЗОПАСНЫЙ ИМПОРТ НОВЫХ МОДУЛЕЙ ===
# Проверяем наличие модулей перед импортом
CLIP_AVAILABLE = False
IMAGE_PROCESSOR_AVAILABLE = False

try:
    from utils.clip_client import clip_generate_name, check_clip_service
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client module loaded")
except ImportError as e:
    logger.warning(f"⚠️ CLIP client not available: {e}")
    # Заглушки для функций
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
    # Заглушки для функций
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
    Шаг 1: Скачивает изображение, генерирует 4 варианта и предлагает название
    Возвращает временный ID и превью вариантов
    
    ВАЖНО: Если модули недоступны, падает с fallback на старый метод
    """
    
    # Проверяем доступность необходимых модулей
    if not IMAGE_PROCESSOR_AVAILABLE:
        logger.error("❌ Image processor not available, cannot generate variants")
        raise HTTPException(
            503, 
            "Сервис генерации вариантов временно недоступен. "
            "Используйте стандартное добавление через /add-marketplace"
        )
    
    loop = asyncio.get_event_loop()
    
    try:
        # 1. Поиск изображения на маркетплейсе
        logger.info(f"🔍 Searching marketplace image...")
        found_image, found_title = await loop.run_in_executor(
            None, 
            lambda: get_marketplace_data(payload.url)
        )
        
        if not found_image and ("wildberries" in payload.url or "ozon" in payload.url):
            raise HTTPException(
                400, 
                "Не удалось получить доступ к картинке. "
                "Используйте прямую ссылку на фото (ПКМ → Копировать URL картинки)."
            )
        
        target_url = found_image if found_image else payload.url
        
        # 2. Скачиваем изображение
        logger.info(f"📥 Downloading image from: {target_url}")
        file_bytes = await loop.run_in_executor(
            None,
            lambda: download_image_bytes(target_url)
        )
        
        # Валидация
        valid, error = validate_image_bytes(file_bytes)
        if not valid:
            raise HTTPException(400, error)
        
        # 3. Генерируем 4 варианта обработки
        logger.info(f"🎨 Generating image variants...")
        img = Image.open(BytesIO(file_bytes))
        variants = generate_image_variants(img, output_size=800)
        
        # 4. Генерируем умное название через CLIP (если доступен)
        suggested_name = payload.name if payload.name else "Покупка"
        
        if CLIP_AVAILABLE and check_clip_service():
            logger.info(f"🤖 Generating smart name with CLIP...")
            try:
                # Сначала сохраняем временное изображение для CLIP
                temp_filename = f"temp_{uuid.uuid4().hex}.jpg"
                temp_bytes = convert_variant_to_bytes(variants["original"])
                temp_url = save_image(temp_filename, temp_bytes)
                
                # Получаем публичный URL
                full_url = temp_url
                if not temp_url.startswith('http'):
                    base_url = os.getenv("BASE_URL", "http://localhost:8000")
                    full_url = f"{base_url}{temp_url}"
                
                name_result = clip_generate_name(full_url)
                if name_result.get("success"):
                    suggested_name = name_result["name"]
                    logger.info(f"✅ CLIP suggested name: {suggested_name}")
                
                # Удаляем временный файл
                delete_image(temp_url)
            except Exception as e:
                logger.warning(f"⚠️ CLIP naming failed: {e}")
        else:
            logger.info("⚠️ CLIP service not available, using default name")
        
        # 5. Конвертируем варианты в bytes и создаём превью
        temp_id = uuid.uuid4().hex
        variant_previews = {}
        variant_full = {}
        
        for variant_name, variant_img in variants.items():
            # Полноразмерная версия
            full_bytes = convert_variant_to_bytes(variant_img, quality=85)
            variant_full[variant_name] = full_bytes
            
            # Превью (300x300)
            preview_img = variant_img.copy()
            preview_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            preview_bytes = convert_variant_to_bytes(preview_img, quality=70)
            
            # Сохраняем превью временно
            preview_filename = f"preview_{temp_id}_{variant_name}.jpg"
            preview_url = save_image(preview_filename, preview_bytes)
            variant_previews[variant_name] = preview_url
        
        # 6. Сохраняем в временное хранилище
        VARIANTS_STORAGE[temp_id] = {
            "variants": variant_full,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "url": payload.url,
            "previews": variant_previews
        }
        
        # Очистка старых вариантов
        cleanup_old_variants()
        
        return {
            "temp_id": temp_id,
            "suggested_name": suggested_name,
            "variants": variant_previews,
            "message": "Выберите лучший вариант изображения"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Variant generation failed: {e}")
        raise HTTPException(500, f"Ошибка генерации вариантов: {str(e)}")

@router.post("/select-variant", response_model=ItemResponse)
async def select_and_save_variant(
    payload: SelectVariantPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Шаг 2: Пользователь выбирает вариант, сохраняем в БД
    """
    # Проверяем наличие вариантов
    if payload.temp_id not in VARIANTS_STORAGE:
        raise HTTPException(404, "Варианты не найдены или истекло время")
    
    stored = VARIANTS_STORAGE[payload.temp_id]
    
    # Проверяем владельца
    if stored["user_id"] != user_id:
        raise HTTPException(403, "Нет доступа к этим вариантам")
    
    # Получаем выбранный вариант
    selected_variant = payload.selected_variant
    if selected_variant not in stored["variants"]:
        raise HTTPException(400, f"Неизвестный вариант: {selected_variant}")
    
    logger.info(f"💾 Saving selected variant: {selected_variant}")
    
    # Сохраняем выбранное изображение
    final_bytes = stored["variants"][selected_variant]
    final_filename = f"wardrobe_{uuid.uuid4().hex}.jpg"
    final_url = save_image(final_filename, final_bytes)
    
    # Удаляем превью
    for preview_url in stored["previews"].values():
        try:
            delete_image(preview_url)
        except:
            pass
    
    # Удаляем из временного хранилища
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
    
    logger.info(f"✅ Item saved: id={item.id}, variant={selected_variant}")
    
    return item

