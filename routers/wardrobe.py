import os, uuid, asyncio, re, logging
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageFilter, ImageStat
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as crequests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from .dependencies import get_current_user_id
from pydantic import BaseModel, ConfigDict
from typing import Optional

logger = logging.getLogger(__name__)

# Интеграция с CLIP
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
except ImportError:
    def rate_image_relevance(img, name): return 100.0

router = APIRouter(tags=["Wardrobe"])

class ItemUrlPayload(BaseModel):
    url: str
    name: Optional[str] = ""

class SelectVariantPayload(BaseModel):
    temp_id: str
    selected_variant: str
    name: str

class ItemResponse(BaseModel):
    id: int
    name: str
    image_url: str
    item_type: str
    model_config = ConfigDict(from_attributes=True)

VARIANTS_STORAGE = {}

def get_wb_basket(vol: int) -> str:
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
    if vol < 1656: return "11"
    if vol < 1920: return "12"
    if vol < 2046: return "13"
    if vol < 2190: return "14"
    if vol < 2406: return "15"
    if vol < 2622: return "16"
    if vol < 2838: return "17"
    if vol < 3054: return "18"
    if vol < 3270: return "19"
    if vol < 3486: return "20"
    if vol < 3702: return "21"
    if vol < 3918: return "22"
    if vol < 4134: return "23"
    if vol < 4350: return "24"
    if vol < 4566: return "25"
    if vol < 4782: return "26"
    return "27" if vol < 5000 else "28"

def parse_wildberries(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    # 1. Сначала пробуем API (Быстро, но WB может блокировать)
    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", timeout=4)
        if r.status_code == 200:
            data = r.json().get('data', {}).get('products', [])
            if data:
                title = f"{data[0].get('brand', '')} {data[0].get('name', '')}".strip()
    except: pass

    # 2. Бронебойный парсинг HTML (SEO-теги для репостов)
    if not title or title.lower() == "одежда":
        try:
            r_html = crequests.get(url, impersonate="chrome120", timeout=5)
            soup = BeautifulSoup(r_html.text, 'html.parser')
            
            # Ищем OpenGraph тег (он есть всегда для репостов в соцсетях)
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title.get('content')
            else:
                title_tag = soup.find('title')
                if title_tag: title = title_tag.get_text(strip=True)
            
            # Очищаем название от рекламного мусора
            if title:
                title = re.sub(r' — купить.*', '', title, flags=re.IGNORECASE)
                title = title.replace('Wildberries', '').replace('Интернет-магазин', '').strip(' -—,')
        except Exception as e:
            logger.error(f"HTML parse error: {e}")

    if not title or len(title) < 2: 
        title = "Вещь из Wildberries"

    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    
    # Берем до 12 фото (на новых товарах их часто много)
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 13)]
    return image_urls, title

def process_single_image(idx, url, item_name):
    """Качественная фильтрация фото с жестким отсевом инфографики"""
    try:
        resp = crequests.get(url, impersonate="chrome120", timeout=8)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # 1. Жесткий детектор текста и таблиц (Инфографика)
        img_gray = img.convert("L")
        edges = img_gray.filter(ImageFilter.FIND_EDGES)
        edge_density = ImageStat.Stat(edges).mean[0]
        
        # Снизили порог с 48 до 35. Любое фото с таблицей размеров улетит в мусор.
        if edge_density > 35:
            logger.info(f"🚫 Скип: фото {idx} - много текста/линий (Edges: {edge_density:.1f})")
            return None

        # 2. Оценка нейросетью CLIP
        preview = img.copy()
        preview.thumbnail((336, 336))
        # Передаем чистое название, чтобы CLIP понимал, что ищет
        score = rate_image_relevance(preview, item_name or "clothing photography without text")
        
        # Повысили минимальный порог
        if CLIP_AVAILABLE and score < 28:
            logger.info(f"🚫 Скип: фото {idx} - не одежда (CLIP: {score:.1f})")
            return None
            
        out = BytesIO()
        preview.save(out, format="JPEG", quality=85)
        
        return {
            "key": f"v_{idx}",
            "url": url,
            "data": out.getvalue(),
            "score": score,
            "is_primary": idx <= 2 # Первые фото в WB обычно лучшие
        }
    except Exception as e:
        return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    image_urls, suggested_title = parse_wildberries(payload.url)
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(executor, process_single_image, i, url, suggested_title) for i, url in enumerate(image_urls)]
        results = [r for r in await asyncio.gather(*tasks) if r]

    if not results:
        raise HTTPException(400, "Не удалось найти подходящие фото товара")

    # Сортировка: Сначала те, у кого score выше, но с учетом "первичности"
    results.sort(key=lambda x: (x['is_primary'], x['score']), reverse=True)

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
        "suggested_name": suggested_title[:60],
        "variants": previews
    }

@router.post("/select-variant", response_model=ItemResponse)
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(404, "Варианты устарели")
    
    # Скачиваем оригинал выбранного варианта
    orig_url = data["urls"].get(payload.selected_variant)
    r = crequests.get(orig_url, impersonate="chrome120")
    
    final_img = Image.open(BytesIO(r.content)).convert("RGB")
    out = BytesIO()
    final_img.save(out, format="JPEG", quality=90)
    
    final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", out.getvalue())
    
    # Удаление временных
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
    return item

