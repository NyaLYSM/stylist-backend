import os
import uuid
import time
import asyncio
import re
import logging
import json
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageStat, ImageFilter

import requests
import concurrent.futures
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

# === ИНИЦИАЛИЗАЦИЯ LOGGER ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ИМПОРТ ML МОДУЛЕЙ ===
CLIP_AVAILABLE = False
try:
    from utils.clip_client import clip_check_clothing, rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client module loaded")
except ImportError:
    logger.warning("⚠️ CLIP module not found. Smart sorting disabled.")
    def rate_image_relevance(img, name): return 50.0

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

# --- Smart Title Extraction ---
def extract_smart_title(full_title: str) -> str:
    """
    Чистит название товара, оставляя только суть для CLIP.
    Пример: "Платье женское вечернее черное оверсайз - купить..." -> "Платье вечернее черное"
    """
    if not full_title: return "clothing"
    
    # 1. Очистка от мусора магазинов
    cleanup_patterns = [
        r'[-|–].*wildberries.*', r'[-|–].*ozon.*', r'[-|–].*lamoda.*',
        r'купить в .*', r'интернет-магазин.*', r'официальный сайт.*',
        r'wildberries', 'wb', 'ozon', 'lamoda', 'aliexpress'
    ]
    
    title = full_title.lower()
    for pat in cleanup_patterns:
        title = re.sub(pat, '', title)

    # 2. Стоп-слова (шум)
    stop_words = [
        'товар', 'цена', 'скидка', 'акция', 'новинка', 'хит', 'new', 'sale',
        'быстрая', 'доставка', 'бесплатная', 'женские', 'мужские', 'детские',
        'для', 'женщин', 'мужчин', 'девочек', 'мальчиков', 'одежда',
        'размер', 'цвет', 'артикул', 'шт', 'уп'
    ]
    
    for w in stop_words:
        title = re.sub(rf'\b{w}\b', '', title)
        
    # 3. Финальная чистка
    title = re.sub(r'[^\w\s]', ' ', title) # Убираем спецсимволы
    title = re.sub(r'\s+', ' ', title).strip() # Убираем двойные пробелы
    
    # Берем первые 5-6 слов, обычно это "Суть + Характеристики"
    words = title.split()
    if not words: return "clothing"
    
    result = ' '.join(words[:6])
    return result.capitalize()

# --- Image Tools ---
def is_valid_image_url(url: str) -> bool:
    """Фильтрует явный мусор в URL"""
    if not url or not url.startswith('http'): return False
    # Игнорируем иконки, svg, gif (обычно лоадеры)
    if any(x in url.lower() for x in ['.svg', '.gif', 'icon', 'logo', 'loader', 'blank']):
        return False
    return True

def analyze_image_score(img: Image.Image, index: int, total_images: int) -> float:
    """Оценивает качество изображения (Эвристика)"""
    score = 100.0
    
    # Штраф за позицию (чем дальше, тем меньше шанс, что это хорошее фото)
    if index > 2: score -= (index * 5)
    
    # Штраф за размер (слишком мелкие или слишком вытянутые баннеры)
    w, h = img.size
    if w < 300 or h < 300: score -= 50
    aspect = w / h
    if aspect > 1.8 or aspect < 0.4: score -= 30 # Баннеры
    
    # Штраф за "шум" (текст/таблицы)
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_density = ImageStat.Stat(edges).mean[0]
    
    if edge_density > 50: 
        score -= 40 # Скорее всего таблица размеров или текст
        
    return max(0, score)

# --- MARKETPLACE PARSERS ---

def parse_wildberries(url: str, logger) -> tuple[list, str]:
    """Специализированный парсер для Wildberries"""
    image_urls = []
    title = None
    nm_id = None
    
    # 1. Извлекаем ID
    match = re.search(r'catalog/(\d+)', url)
    if match: nm_id = int(match.group(1))
    
    if not nm_id: return [], None

    # 2. Стратегия A: Mobile API
    try:
        # Используем card.wb.ru
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={nm_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        }
        resp = requests.get(api_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            products = data.get('data', {}).get('products', [])
            if products:
                prod = products[0]
                title = prod.get('name')
                
                # Генерация ссылок (basket-01 ... basket-75)
                # РАСШИРЯЕМ ДИАПАЗОН ОБРАТНО, иначе новые товары не найдутся!
                vol = nm_id // 100000
                part = nm_id // 1000
                hosts = [f"basket-{i:02d}.wbbasket.ru" for i in range(1, 76)] 
                
                # Быстрый поиск рабочего хоста (Head request)
                found_host = None
                
                # Пробуем сначала последние сервера (там чаще новые товары)
                for h in reversed(hosts):
                    test_url = f"https://{h}/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
                    try:
                        # Очень короткий таймаут, чтобы быстро перебирать
                        if requests.head(test_url, timeout=0.2).status_code == 200:
                            found_host = h
                            break
                    except: continue
                
                if found_host:
                    # Если нашли хост, генерируем ссылки
                    for i in range(1, 15):
                        image_urls.append(f"https://{found_host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp")
                    
                    logger.info(f"✅ WB Strategy Success: Host={found_host}")
                    return image_urls, title
    except Exception as e:
        logger.warning(f"⚠️ WB API Strategy failed: {e}")

    # 3. Fallback
    return parse_generic_json_ld(url, logger)

def parse_generic_json_ld(url: str, logger) -> tuple[list, str]:
    """
    Универсальный парсер для Ozon, Lamoda и других сайтов, 
    использующих Schema.org (JSON-LD) или Open Graph.
    """
    image_urls = []
    title = None
    
    try:
        # Имитируем реальный браузер
        resp = crequests.get(
            url, 
            impersonate="chrome120", 
            headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8"},
            timeout=10
        )
        
        if resp.status_code != 200: return [], None
        
        soup = BeautifulSoup(resp.content, "lxml")
        
        # A. Ищем JSON-LD (Schema.org) - Золотой стандарт
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0] # Иногда это список
                
                # Ищем объект типа Product
                if isinstance(data, dict):
                    # Название
                    if not title and 'name' in data:
                        title = data['name']
                    
                    # Картинки
                    if 'image' in data:
                        imgs = data['image']
                        if isinstance(imgs, str): image_urls.append(imgs)
                        elif isinstance(imgs, list): image_urls.extend(imgs)
            except: pass

        # B. Ищем Open Graph (og:title, og:image) - Серебряный стандарт
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title: title = og_title.get("content")
            
        # Добираем картинки из OG, если пусто
        if not image_urls:
            og_img = soup.find("meta", property="og:image")
            if og_img: image_urls.append(og_img.get("content"))

        # C. Ищем <title> и <h1> - Бронзовый стандарт
        if not title:
            if soup.title: title = soup.title.string
            elif soup.find("h1"): title = soup.find("h1").get_text(strip=True)

        # D. "Пылесосим" картинки из HTML, если совсем пусто (для Lamoda/Ozon часто нужно)
        if len(image_urls) < 2:
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if is_valid_image_url(src):
                    # Фильтр по размеру (простейший, по имени файла или атрибутам)
                    if 'icon' not in src and 'logo' not in src:
                        image_urls.append(src)

    except Exception as e:
        logger.error(f"❌ Generic Parser Error: {e}")
        
    # Чистим дубли
    image_urls = list(dict.fromkeys(image_urls))
    return image_urls[:15], title

# --- MAIN CONTROLLER ---

def get_marketplace_data(url: str):
    """Маршрутизатор: выбирает правильный парсер для ссылки"""
    logger.info(f"🌐 Processing URL: {url}")
    
    if "wildberries" in url or "wb.ru" in url:
        return parse_wildberries(url, logger)
    
    elif "ozon" in url:
        return parse_generic_json_ld(url, logger)
        
    elif "lamoda" in url:
        return parse_generic_json_ld(url, logger)
        
    else:
        return parse_generic_json_ld(url, logger)

def download_image_bytes(image_url: str) -> bytes:
    """Безопасное скачивание"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/'
    }
    try:
        resp = requests.get(image_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Download failed {image_url}: {e}")
    return None

# --- API ENDPOINTS ---

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(
    payload: ItemUrlPayload, 
    db: Session = Depends(get_db), 
    user_id: int = Depends(get_current_user_id)
):
    loop = asyncio.get_event_loop()
    
    # === ИСПРАВЛЕНИЕ: Запускаем синхронный парсер в отдельном потоке ===
    # Это предотвращает блокировку сервера и исправляет ошибку вызова
    try:
        image_urls, full_title = await loop.run_in_executor(
            None, 
            lambda: get_marketplace_data(payload.url)
        )
    except Exception as e:
        logger.error(f"❌ Parser crashed: {e}")
        raise HTTPException(400, f"Ошибка при чтении ссылки: {str(e)}")

    if not image_urls:
        logger.warning(f"❌ No images found for {payload.url}")
        raise HTTPException(400, "Не удалось найти изображения. Попробуйте обновить страницу товара или загрузить фото вручную.")

    # ... Дальше код без изменений ...
    
    # Подготовка Prompt для CLIP
    raw_name = payload.name if payload.name else (full_title if full_title else "clothing")
    clip_prompt = extract_smart_title(raw_name)
    
    logger.info(f"🧠 CLIP Search Prompt: '{clip_prompt}'")

    # 3. Анализ изображений
    temp_id = uuid.uuid4().hex
    candidates = []
    
    process_urls = image_urls[:10]
    
    for idx, img_url in enumerate(process_urls):
        try:
            file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(img_url))
            if not file_bytes: continue
            
            # Конвертация в RGB
            img = Image.open(BytesIO(file_bytes))
            if img.mode != 'RGB':
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode in ('RGBA', 'LA'):
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg

            heuristic_score = analyze_image_score(img, idx, len(process_urls))
            
            clip_score = 0.0
            if CLIP_AVAILABLE and heuristic_score > 20: 
                clip_score = await loop.run_in_executor(
                    None,
                    lambda: rate_image_relevance(img, clip_prompt)
                )
            
            final_score = (heuristic_score * 0.3) + (clip_score * 0.7)
            
            preview_img = img.copy()
            preview_img.thumbnail((400, 400))
            out = BytesIO()
            preview_img.save(out, format='JPEG', quality=85)
            
            candidates.append({
                "score": final_score,
                "original_url": img_url,
                "preview_bytes": out.getvalue(),
                "original_idx": idx
            })
            
            logger.info(f"Img {idx+1}: Score={final_score:.1f} (CLIP={clip_score:.1f})")
            
        except Exception as e:
            logger.warning(f"Skipping img {idx}: {e}")

    # Сортировка и сохранение
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:4]
    top_candidates.sort(key=lambda x: x["original_idx"])
    
    variant_previews = {}
    variant_full_urls = {}
    
    for cand in top_candidates:
        v_key = f"v_{cand['original_idx']}"
        fname = f"prev_{temp_id}_{v_key}.jpg"
        url = save_image(fname, cand['preview_bytes'])
        
        variant_previews[v_key] = url
        variant_full_urls[v_key] = cand['original_url']

    if not variant_previews:
         raise HTTPException(400, "Не удалось обработать изображения (возможно, защита сайта).")

    VARIANTS_STORAGE[temp_id] = {
        "image_urls": variant_full_urls,
        "previews": variant_previews,
        "user_id": user_id,
        "created_at": datetime.utcnow()
    }
    
    display_name = full_title if full_title else "Новая вещь"
    if len(display_name) > 60: display_name = display_name[:57] + "..."

    return {
        "temp_id": temp_id,
        "suggested_name": display_name,
        "variants": variant_previews,
        "total_images": len(variant_previews)
    }

@router.post("/select-variant", response_model=ItemResponse)
async def select_variant(
    payload: SelectVariantPayload,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    if payload.temp_id not in VARIANTS_STORAGE:
        raise HTTPException(404, "Session expired")
    
    data = VARIANTS_STORAGE[payload.temp_id]
    if data["user_id"] != user_id: raise HTTPException(403, "Access denied")
    
    target_url = data["image_urls"].get(payload.selected_variant)
    if not target_url: raise HTTPException(400, "Invalid variant")
    
    loop = asyncio.get_event_loop()
    file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(target_url))
    
    if not file_bytes: raise HTTPException(400, "Failed to download original")
    
    img = Image.open(BytesIO(file_bytes))
    if img.mode != 'RGB': img = img.convert('RGB') # Fix RGBA again just in case
    
    out = BytesIO()
    img.save(out, format='JPEG', quality=95)
    
    fname = f"item_{uuid.uuid4().hex}.jpg"
    final_url = save_image(fname, out.getvalue())
    
    # Cleanup
    for p_url in data["previews"].values():
        try: delete_image(p_url)
        except: pass
    del VARIANTS_STORAGE[payload.temp_id]
    
    item = WardrobeItem(
        user_id=user_id,
        name=payload.name,
        item_type="marketplace",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item); db.commit(); db.refresh(item)
    return item

# --- Старые роуты (оставлены для совместимости) ---
@router.get("/items", response_model=list[ItemResponse]) 
def get_wardrobe_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.created_at.desc()).all()
    return items if items else []

@router.delete("/delete")
def delete_item(item_id: int, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item: raise HTTPException(404, "Not found")
    try: delete_image(item.image_url)
    except: pass
    db.delete(item); db.commit()
    return {"status": "success"}

