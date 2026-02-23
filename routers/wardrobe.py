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
    """Чистит название товара для CLIP"""
    if not full_title: return "clothing"
    
    cleanup_patterns = [
        r'[-|–].*wildberries.*', r'[-|–].*ozon.*', r'[-|–].*lamoda.*',
        r'купить в .*', r'интернет-магазин.*', r'официальный сайт.*',
        r'wildberries', 'wb', 'ozon', 'lamoda', 'aliexpress'
    ]
    
    title = full_title.lower()
    for pat in cleanup_patterns:
        title = re.sub(pat, '', title)

    stop_words = [
        'товар', 'цена', 'скидка', 'акция', 'новинка', 'хит', 'new', 'sale',
        'быстрая', 'доставка', 'бесплатная', 'женские', 'мужские', 'детские',
        'для', 'женщин', 'мужчин', 'девочек', 'мальчиков', 'одежда',
        'размер', 'цвет', 'артикул', 'шт', 'уп'
    ]
    
    for w in stop_words:
        title = re.sub(rf'\b{w}\b', '', title)
        
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    
    words = title.split()
    if not words: return "clothing"
    
    result = ' '.join(words[:6])
    return result.capitalize()

# --- Image Tools ---
def is_valid_image_url(url: str) -> bool:
    if not url or not url.startswith('http'): return False
    if any(x in url.lower() for x in ['.svg', '.gif', 'icon', 'logo', 'loader', 'blank']):
        return False
    return True

def analyze_image_score(img: Image.Image, index: int, total_images: int) -> float:
    score = 100.0
    if index > 2: score -= (index * 5)
    
    w, h = img.size
    if w < 300 or h < 300: score -= 50
    aspect = w / h
    if aspect > 1.8 or aspect < 0.4: score -= 30 
    
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_density = ImageStat.Stat(edges).mean[0]
    
    if edge_density > 50: score -= 40
    return max(0, score)

# --- MARKETPLACE PARSERS (SYNCHRONOUS) ---

def get_wb_basket(vol: int) -> str:
    """Официальная математика маршрутизации серверов Wildberries. Работает мгновенно."""
    if 0 <= vol <= 143: return "01"
    if 144 <= vol <= 287: return "02"
    if 288 <= vol <= 431: return "03"
    if 432 <= vol <= 719: return "04"
    if 720 <= vol <= 1007: return "05"
    if 1008 <= vol <= 1061: return "06"
    if 1062 <= vol <= 1115: return "07"
    if 1116 <= vol <= 1169: return "08"
    if 1170 <= vol <= 1313: return "09"
    if 1314 <= vol <= 1601: return "10"
    if 1602 <= vol <= 1655: return "11"
    if 1656 <= vol <= 1919: return "12"
    if 1920 <= vol <= 2045: return "13"
    if 2046 <= vol <= 2189: return "14"
    if 2190 <= vol <= 2405: return "15"
    if 2406 <= vol <= 2621: return "16"
    if 2622 <= vol <= 2837: return "17"
    if 2838 <= vol <= 3053: return "18"
    if 3054 <= vol <= 3269: return "19"
    if 3270 <= vol <= 3485: return "20"
    if 3486 <= vol <= 3701: return "21"
    if 3702 <= vol <= 3917: return "22"
    if 3918 <= vol <= 4133: return "23"
    if 4134 <= vol <= 4349: return "24"
    if 4350 <= vol <= 4565: return "25"
    if 4566 <= vol <= 4781: return "26"
    if 4782 <= vol <= 4997: return "27"
    if 4998 <= vol <= 5213: return "28"
    if 5214 <= vol <= 5429: return "29"
    if 5430 <= vol <= 5645: return "30"
    if 5646 <= vol <= 5861: return "31"
    if 5862 <= vol <= 6077: return "32"
    if 6078 <= vol <= 6293: return "33"
    if 6294 <= vol <= 6509: return "34"
    if 6510 <= vol <= 6725: return "35"
    if 6726 <= vol <= 6941: return "36"
    # Для новейших товаров WB использует формулу +1 к номеру корзины каждые 216 vol
    return str(37 + (vol - 6942) // 216).zfill(2)

def parse_wildberries(url: str, logger) -> tuple[list, str]:
    """
    Версия 7.0: Математическая Маршрутизация.
    БЕЗ брутфорса серверов. Идеально обходит блокировки.
    """
    image_urls = []
    title = None
    nm_id = None
    pics_count = 10 # По умолчанию скачиваем 10 превью
    
    match = re.search(r'catalog/(\d+)', url)
    if match: nm_id = int(match.group(1))
    
    if not nm_id: return [], None

    vol = nm_id // 100000
    part = nm_id // 1000

    # 1. Безопасный запрос через crequests (имитация Chrome обходит WAF WB)
    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={nm_id}"
        resp = crequests.get(api_url, impersonate="chrome120", timeout=5)
        
        if resp.status_code == 200:
            data = resp.json()
            products = data.get('data', {}).get('products', [])
            if products:
                prod = products[0]
                title = prod.get('name')
                # WB API говорит нам точное количество фото товара
                pics_count = prod.get('pics', 10) 
                if title: logger.info(f"✅ WB API Success. Title: '{title}', Pics: {pics_count}")
    except Exception as e:
        logger.warning(f"⚠️ WB API fetch warning: {e}")

    # 2. Мгновенно вычисляем сервер математически
    basket_id = get_wb_basket(vol)
    
    # Старые товары часто лежат на .wb.ru, а новые на .wbbasket.ru. 
    # Делаем всего ОДИН быстрый проверочный запрос нужного домена.
    host = f"basket-{basket_id}.wbbasket.ru"
    try:
        test_url = f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
        if crequests.head(test_url, impersonate="chrome120", timeout=3).status_code != 200:
            host = f"basket-{basket_id}.wb.ru"
    except:
        host = f"basket-{basket_id}.wb.ru"
        
    logger.info(f"✅ Calculated Image Server: {host}")
    
    # 3. Генерируем точное количество ссылок
    for i in range(1, pics_count + 1):
        image_urls.append(f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp")
        
    # 4. Если всё-таки API не отдало название, используем HTML fallback
    if not title:
        logger.info("⚠️ Title missing from API. Running HTML fallback...")
        _, title = parse_generic_json_ld(url, logger)
        
    return image_urls, title
    
def parse_generic_json_ld(url: str, logger) -> tuple[list, str]:
    """Универсальный парсер (JSON-LD / OG)"""
    image_urls = []
    title = None
    
    try:
        resp = crequests.get(
            url, 
            impersonate="chrome120", 
            headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8"},
            timeout=10
        )
        
        if resp.status_code != 200: return [], None
        
        soup = BeautifulSoup(resp.content, "lxml")
        
        # A. JSON-LD
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0]
                
                if isinstance(data, dict):
                    if not title and 'name' in data: title = data['name']
                    if 'image' in data:
                        imgs = data['image']
                        if isinstance(imgs, str): image_urls.append(imgs)
                        elif isinstance(imgs, list): image_urls.extend(imgs)
            except: pass

        # B. Open Graph
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title: title = og_title.get("content")
            
        if not image_urls:
            og_img = soup.find("meta", property="og:image")
            if og_img: image_urls.append(og_img.get("content"))

        # C. Title Tag
        if not title:
            if soup.title: title = soup.title.string
            elif soup.find("h1"): title = soup.find("h1").get_text(strip=True)

        # D. HTML Scraping
        if len(image_urls) < 2:
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if is_valid_image_url(src):
                    if 'icon' not in src and 'logo' not in src:
                        image_urls.append(src)

    except Exception as e:
        logger.error(f"❌ Generic Parser Error: {e}")
        
    image_urls = list(dict.fromkeys(image_urls))
    return image_urls[:15], title

# === MAIN CONTROLLER (SYNCHRONOUS) ===

def get_marketplace_data(url: str):
    """Маршрутизатор (Синхронный)"""
    logger.info(f"🌐 Processing URL: {url}")
    
    if "wildberries" in url or "wb.ru" in url:
        return parse_wildberries(url, logger)
    elif "ozon" in url or "lamoda" in url or "aliexpress" in url:
        return parse_generic_json_ld(url, logger)
    else:
        return parse_generic_json_ld(url, logger)

def download_image_bytes(image_url: str) -> bytes:
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
    
    # 1. Запуск парсера (В отдельном потоке)
    try:
        # ВАЖНО: Вызываем синхронную функцию get_marketplace_data
        image_urls, full_title = await loop.run_in_executor(
            None, 
            lambda: get_marketplace_data(payload.url)
        )
    except Exception as e:
        logger.error(f"❌ Parser crashed: {e}")
        raise HTTPException(400, f"Ошибка обработки ссылки: {str(e)}")

    if not image_urls:
        logger.warning(f"❌ No images found for {payload.url}")
        raise HTTPException(400, "Не удалось найти изображения. Попробуйте обновить страницу товара.")

    # 2. Подготовка CLIP
    raw_name = payload.name if payload.name else (full_title if full_title else "clothing")
    clip_prompt = extract_smart_title(raw_name)
    logger.info(f"🧠 CLIP Prompt: '{clip_prompt}'")

    # 3. Анализ (Скачивание и обработка)
    temp_id = uuid.uuid4().hex
    candidates = []
    process_urls = image_urls[:10]
    
    for idx, img_url in enumerate(process_urls):
        try:
            file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(img_url))
            if not file_bytes: continue
            
            # Конвертация RGBA -> RGB
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

    # 4. Сортировка и ответ
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
         raise HTTPException(400, "Не удалось обработать изображения.")

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
        raise HTTPException(404, "Время сессии истекло")
    
    data = VARIANTS_STORAGE[payload.temp_id]
    if data["user_id"] != user_id: raise HTTPException(403, "Нет доступа")
    
    target_url = data["image_urls"].get(payload.selected_variant)
    if not target_url: raise HTTPException(400, "Неверный вариант")
    
    loop = asyncio.get_event_loop()
    file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(target_url))
    
    if not file_bytes: raise HTTPException(400, "Ошибка скачивания оригинала")
    
    img = Image.open(BytesIO(file_bytes))
    if img.mode != 'RGB': img = img.convert('RGB')
    
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





