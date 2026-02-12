import os
import uuid
import time
import asyncio
import re
import logging
import json # <--- Добавлено для JSON-LD
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageStat, ImageFilter

# requests - для проверки доступности и скачивания
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

# === ИНИЦИАЛИЗАЦИЯ LOGGER СНАЧАЛА ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ИМПОРТ НОВЫХ МОДУЛЕЙ ===
CLIP_AVAILABLE = False
IMAGE_PROCESSOR_AVAILABLE = False

try:
    from utils.clip_client import clip_check_clothing, rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client module loaded")
except ImportError:
    CLIP_AVAILABLE = False
    def rate_image_relevance(img, name): return 50.0

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

def analyze_image_score(img: Image.Image, index: int, total_images: int) -> float:
    """
    Оценивает пригодность изображения для гардероба (0-100).
    """
    score = 100.0
    
    # 1. Штраф за позицию (WB ставит лучшие фото первыми)
    if index > 2:
        score -= (index * 5)
    
    # 2. Штраф для последних фото (таблицы размеров)
    if index >= total_images - 1 and total_images > 3:
        score -= 20

    # Конвертируем в ч/б для анализа
    gray = img.convert("L")
    
    # 3. Детектор таблиц и текста
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edges)
    edge_density = edge_stat.mean[0]
    
    # Если слишком много линий (текст, таблица) -> штраф
    if edge_density > 50: 
        score -= 40
        logger.info(f"📉 Image {index+1}: High edge density ({edge_density:.1f}) -> Likely table")
        
    return score

def find_wb_image_url(nm_id: int) -> str:
    """Поиск изображений WB на разных серверах"""
    vol = nm_id // 100000
    part = nm_id // 1000
    # Расширенный список хостов
    hosts = [f"basket-{i:02d}.wbbasket.ru" for i in range(1, 75)]
    
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'}

    # Сначала пробуем сформировать URL быстро, если знаем паттерн
    # (Оптимизация: обычно новые товары лежат на последних серверах, старые на первых)
    
    url_templates = ["https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.webp"]

    def check_url(url):
        try:
            resp = requests.head(url, headers=headers, timeout=0.5)
            if resp.status_code == 200: return url
        except: pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        all_urls = []
        for host in hosts:
            all_urls.append(url_templates[0].format(host=host, vol=vol, part=part, nm_id=nm_id))
        
        future_to_url = {executor.submit(check_url, url): url for url in all_urls}
        for future in concurrent.futures.as_completed(future_to_url):
            result = future.result()
            if result:
                executor.shutdown(wait=False, cancel_futures=True)
                return result
    return None
    
def extract_smart_title(full_title: str) -> str:
    """Чистит название товара для CLIP"""
    if not full_title: return "clothing"
    
    title = full_title.lower()
    # Убираем лишнее
    title = re.sub(r'[\/\-]', ' ', title) # Заменяем слеши и дефисы пробелами
    
    stop_words = [
        'wildberries', 'wb', 'ozon', 'товар', 'купить', 'цена', 'скидка', 
        'женские', 'женская', 'мужские', 'мужская', 'детские', 
        'размер', 'цвет', 'новинка', 'хит', '2024', '2025', '2026'
    ]
    
    for w in stop_words:
        title = title.replace(w, '')
        
    # Убираем цифры (артикулы)
    title = re.sub(r'\b\d+\b', '', title)
    
    # Берем первые 4 слова - обычно там суть (напр. "Платье вечернее черное в пол")
    words = [w for w in title.split() if len(w) > 2]
    result = ' '.join(words[:4]).strip()
    
    return result.capitalize() if result else "clothing"

def get_marketplace_data(url: str):
    """
    Получает изображения и название товара.
    Улучшенная логика для WB и JSON-LD.
    """
    logger.info(f"🌐 Processing URL: {url}")
    image_urls = []
    title = None
    
    # === WILDBERRIES ===
    if "wildberries" in url or "wb.ru" in url:
        try:
            match = re.search(r'catalog/(\d+)', url)
            if match:
                nm_id = int(match.group(1))
                
                # 1. WB API v2 (с безопасными параметрами dest=-1)
                # dest=-1 работает почти везде и не требует точной локации
                card_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1&spp=30&nm={nm_id}"
                try:
                    res = requests.get(card_url, timeout=5)
                    if res.status_code == 200:
                        data = res.json()
                        product = data.get('data', {}).get('products', [{}])[0]
                        
                        # Название
                        title = product.get('name')
                        if not title: title = product.get('brand', '') + ' ' + product.get('name', '')
                        
                        # Кол-во фото
                        pics_count = product.get('pics', 0)
                        logger.info(f"✅ WB API: Title='{title}', Pics={pics_count}")
                except Exception as e:
                    logger.warning(f"⚠️ WB API failed: {e}")

                # 2. Если API не сработало, ищем картинки перебором
                base_url = find_wb_image_url(nm_id)
                if base_url:
                    host_match = re.search(r'basket-\d+\.wbbasket\.ru', base_url)
                    if host_match:
                        host = host_match.group(0)
                        vol = nm_id // 100000
                        part = nm_id // 1000
                        
                        count = locals().get('pics_count', 12) # Если API отвалилось, берем 12
                        if count == 0: count = 12

                        for i in range(1, count + 1):
                            image_urls.append(f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp")
            
            # Если название все еще нет, пробуем парсить страницу через curl_cffi
            if not title:
                try:
                    resp = crequests.get(url, impersonate="chrome120", timeout=8)
                    soup = BeautifulSoup(resp.content, "lxml")
                    
                    # Поиск h1
                    h1 = soup.find("h1")
                    if h1: title = h1.get_text(strip=True)
                except: pass

        except Exception as e:
            logger.error(f"❌ WB Error: {e}")

    # === ОБЩИЙ ПАРСИНГ (OZON, LAMODA и т.д.) ===
    else:
        try:
            resp = crequests.get(url, impersonate="chrome120", timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "lxml")
                
                # 1. JSON-LD (Самый надежный способ для SEO сайтов)
                if not title:
                    scripts = soup.find_all('script', type='application/ld+json')
                    for script in scripts:
                        try:
                            data = json.loads(script.string)
                            # Ищем Product schema
                            if isinstance(data, dict) and data.get('@type') == 'Product':
                                title = data.get('name')
                                # Если есть картинка в схеме
                                if 'image' in data:
                                    img = data['image']
                                    if isinstance(img, str): image_urls.append(img)
                                    elif isinstance(img, list): image_urls.extend(img)
                                break
                            # Иногда это список
                            elif isinstance(data, list):
                                for item in data:
                                    if item.get('@type') == 'Product':
                                        title = item.get('name')
                                        break
                        except: pass

                # 2. Open Graph
                if not title:
                    og = soup.find("meta", property="og:title")
                    if og: title = og.get("content")
                
                # 3. H1
                if not title:
                    h1 = soup.find("h1")
                    if h1: title = h1.get_text(strip=True)

                # Поиск картинок (если еще нет)
                if not image_urls:
                    for img in soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if src and src.startswith('http') and ('large' in src or 'big' in src or 'gallery' in src):
                            image_urls.append(src)

        except Exception as e:
            logger.error(f"❌ General parser error: {e}")

    final_title = title.strip() if title else None
    return image_urls, final_title

def download_image_bytes(image_url: str) -> bytes:
    """Скачивание с User-Agent"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.wildberries.ru/' # Часто помогает
    }
    try:
        resp = requests.get(image_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        logger.warning(f"Download failed {image_url}: {e}")
    return None

# --- Main Endpoints ---

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(
    payload: ItemUrlPayload, 
    db: Session = Depends(get_db), 
    user_id: int = Depends(get_current_user_id)
):
    loop = asyncio.get_event_loop()
    
    # 1. Получаем данные
    image_urls, full_title = await loop.run_in_executor(
        None, 
        lambda: get_marketplace_data(payload.url)
    )
    
    if not image_urls:
        raise HTTPException(400, "Изображения не найдены. Проверьте ссылку.")

    # Используем имя из payload если есть, иначе найденное, иначе "clothing"
    # Но для CLIP нам нужно очищенное название
    raw_name = payload.name if payload.name else (full_title if full_title else "clothing")
    
    # Подготовка названия для CLIP (самое важное!)
    clip_prompt = extract_smart_title(raw_name)
    logger.info(f"🧠 CLIP Search Prompt: '{clip_prompt}' (Original: {raw_name[:30]}...)")

    image_urls = image_urls[:10] # Берем топ-10
    temp_id = uuid.uuid4().hex
    candidates = []

    # 2. Анализ
    for idx, img_url in enumerate(image_urls):
        try:
            file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(img_url))
            if not file_bytes: continue
            
            # --- FIX RGBA HERE ---
            img = Image.open(BytesIO(file_bytes))
            # СРАЗУ конвертируем в RGB, чтобы избежать ошибок "cannot write mode RGBA as JPEG" в дальнейшем
            if img.mode != 'RGB':
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode in ('RGBA', 'LA'):
                    bg.paste(img, mask=img.split()[-1])
                else:
                    bg.paste(img)
                img = bg

            # Эвристика
            heuristic_score = analyze_image_score(img, idx, len(image_urls))
            
            # CLIP
            clip_score = 0.0
            if CLIP_AVAILABLE and heuristic_score > 20:
                clip_score = await loop.run_in_executor(
                    None,
                    lambda: rate_image_relevance(img, clip_prompt) # <-- Передаем правильный промпт
                )
            
            # Финальная формула: CLIP важнее (70%), эвристика вспомогательная (30%)
            # Если CLIP нашел точное совпадение, оно перевесит порядок фото
            final_score = (heuristic_score * 0.3) + (clip_score * 0.7)
            
            # Создаем превью
            preview_img = img.copy()
            preview_img.thumbnail((400, 400)) # Чуть больше для качества
            
            out = BytesIO()
            preview_img.save(out, format='JPEG', quality=80)
            preview_bytes = out.getvalue()
            
            candidates.append({
                "score": final_score,
                "original_url": img_url,
                "preview_bytes": preview_bytes,
                "original_idx": idx
            })
            
            logger.info(f"Img {idx+1}: Score={final_score:.1f} (CLIP={clip_score:.1f})")
            
        except Exception as e:
            logger.warning(f"Error processing img {idx}: {e}")

    # 3. Выбор лучших
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:4]
    
    # Сортируем топ по оригинальному порядку (чтобы не прыгали цвета)
    top_candidates.sort(key=lambda x: x["original_idx"])

    # Сохраняем превью
    variant_previews = {}
    variant_full_urls = {}
    
    for cand in top_candidates:
        v_key = f"v_{cand['original_idx']}"
        fname = f"prev_{temp_id}_{v_key}.jpg"
        url = save_image(fname, cand["preview_bytes"])
        
        variant_previews[v_key] = url
        variant_full_urls[v_key] = cand["original_url"]

    VARIANTS_STORAGE[temp_id] = {
        "image_urls": variant_full_urls,
        "previews": variant_previews,
        "user_id": user_id,
        "created_at": datetime.utcnow()
    }
    
    # Возвращаем красивое имя пользователю
    display_name = full_title if full_title else "Новая вещь"
    if len(display_name) > 50: display_name = display_name[:47] + "..."

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
    
    # Скачиваем оригинал
    loop = asyncio.get_event_loop()
    file_bytes = await loop.run_in_executor(None, lambda: download_image_bytes(target_url))
    
    if not file_bytes: raise HTTPException(400, "Failed to download original")
    
    # Конвертируем и сохраняем
    img = Image.open(BytesIO(file_bytes))
    if img.mode != 'RGB': img = img.convert('RGB')
    
    out = BytesIO()
    img.save(out, format='JPEG', quality=90)
    final_bytes = out.getvalue()
    
    fname = f"item_{uuid.uuid4().hex}.jpg"
    final_url = save_image(fname, final_bytes)
    
    # Чистим превью
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

# (Остальные роуты без изменений: items, delete и т.д.)
# ...
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
