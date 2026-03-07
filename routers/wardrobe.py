import os, uuid, asyncio, re, logging, json
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageFilter, ImageStat
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as crequests

# Исправленный блок импорта парсера
try:
    from bs4 import BeautifulSoup
except ImportError:
    logger.error("❌ Критическая ошибка: beautifulsoup4 не установлен!")

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from .dependencies import get_current_user_id
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

# Интеграция с CLIP
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP module loaded")
except ImportError:
    logger.warning("⚠️ CLIP not found. Using dummy scoring.")
    def rate_image_relevance(img, name): return 50.0

router = APIRouter(tags=["Wardrobe"])

class ItemUrlPayload(BaseModel):
    url: str
    name: Optional[str] = ""

class SelectVariantPayload(BaseModel):
    temp_id: str
    selected_variant: str
    name: str

VARIANTS_STORAGE = {}

def get_wb_basket(vol: int) -> str:
    # Упрощенная логика корзин WB
    if vol < 144: return "01"
    if vol < 288: return "02"
    if vol < 432: return "03"
    if vol < 720: return "04"
    if vol < 1008: return "05"
    if vol < 1062: return "06"
    if vol < 1116: return "07"
    if vol < 1170: return "08"
    if vol < 1314: return "09"
    if vol < 1602: return "10"
    return "11"

def extract_smart_category(title: str) -> str:
    """Оставляет только суть: 'Брюки мужские', 'Платье летнее'"""
    if not title or "Wildberries" in title: return "clothing"
    # Убираем мусор и бренды
    text = title.lower()
    text = re.sub(r'[^а-яёa-z\s]', ' ', text)
    words = text.split()
    # Берем первые 2-3 слова — там обычно категория
    return " ".join(words[:3])

def parse_wildberries(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    # 1. Пробуем API
    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", timeout=4)
        if r.status_code == 200:
            data = r.json().get('data', {}).get('products', [])
            if data:
                title = f"{data[0].get('brand', '')} {data[0].get('name', '')}".strip()
    except: pass

    # 2. Бронебойный HTML парсинг (теперь без ошибки BeautifulSoup)
    if not title or "одежда" in title.lower():
        try:
            r_html = crequests.get(url, impersonate="chrome120", timeout=5)
            soup = BeautifulSoup(r_html.text, 'html.parser')
            og_title = soup.find('meta', property='og:title')
            title = og_title.get('content') if og_title else soup.title.string
            title = re.sub(r' — купить.*', '', title, flags=re.I).strip()
        except Exception as e:
            logger.error(f"❌ HTML parse error: {e}")

    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 10)]
    
    return image_urls, title or "Товар Wildberries"

def process_single_image(idx, url, item_category):
    """Фильтрация фото с фокусом на категорию товара"""
    try:
        resp = crequests.get(url, impersonate="chrome120", timeout=8)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # 1. Детектор текста (края)
        img_gray = img.convert("L")
        edges = img_gray.filter(ImageFilter.FIND_EDGES)
        edge_density = ImageStat.Stat(edges).mean[0]
        if edge_density > 35: return None # Таблицы размеров и инфографика в мусор

        # 2. CLIP Scoring
        preview = img.copy()
        preview.thumbnail((336, 336))
        
        # Динамический промпт: ищем именно то, что в названии
        prompt = f"a professional photo of {item_category}, high quality, no text, no captions"
        score = rate_image_relevance(preview, prompt)
        
        # Если CLIP сомневается, что это наш предмет — скипаем
        if score < 25: return None 
            
        out = BytesIO()
        preview.save(out, format="JPEG", quality=85)
        
        return {
            "key": f"v_{idx}",
            "url": url,
            "data": out.getvalue(),
            "score": score,
            "idx": idx
        }
    except: return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    image_urls, full_title = parse_wildberries(payload.url)
    
    # Очищаем название для нейросети
    item_category = extract_smart_category(full_title)
    logger.info(f"🎯 Ищем категорию: {item_category}")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Передаем категорию в каждое фото для точного поиска
        tasks = [loop.run_in_executor(executor, process_single_image, i, url, item_category) 
                 for i, url in enumerate(image_urls)]
        results = [r for r in await asyncio.gather(*tasks) if r]

    if not results:
        raise HTTPException(400, "Чистые фото товара не найдены")

    # Сортируем: сначала те, что больше всего похожи на нашу категорию
    results.sort(key=lambda x: x['score'], reverse=True)

    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for item in results[:6]:
        v_key = item["key"]
        saved_url = save_image(f"t_{temp_id}_{v_key}.jpg", item["data"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}
    
    return {
        "temp_id": temp_id,
        "suggested_name": full_title[:60],
        "variants": previews
    }

@router.post("/select-variant")
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(404, "Сессия истекла")
    
    orig_url = data["urls"].get(payload.selected_variant)
    r = crequests.get(orig_url, impersonate="chrome120")
    
    final_img = Image.open(BytesIO(r.content)).convert("RGB")
    out = BytesIO()
    final_img.save(out, format="JPEG", quality=90)
    
    final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", out.getvalue())
    
    # Очистка временных файлов
    for p_url in data["previews"].values():
        try: delete_image(p_url)
        except: pass
    del VARIANTS_STORAGE[payload.temp_id]

    item = WardrobeItem(
        user_id=user_id,
        name=payload.name,
        image_url=final_url,
        item_type="marketplace",
        created_at=datetime.utcnow()
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "image_url": item.image_url}

@router.get("/items")
def get_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.id.desc()).all()
