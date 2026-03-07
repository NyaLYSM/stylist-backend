import os, uuid, asyncio, re, logging, json
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageFilter, ImageStat
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as crequests

try:
    from bs4 import BeautifulSoup
except ImportError:
    pass

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
    logger.warning("⚠️ CLIP not found. Using dummy scores.")
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

def get_wb_basket(nm_id: int) -> str:
    """Актуальная логика корзин Wildberries (2024-2025)"""
    vol = nm_id // 100000
    if vol <= 143: return "01"
    if vol <= 287: return "02"
    if vol <= 431: return "03"
    if vol <= 719: return "04"
    if vol <= 1007: return "05"
    if vol <= 1061: return "06"
    if vol <= 1115: return "07"
    if vol <= 1169: return "08"
    if vol <= 1313: return "09"
    if vol <= 1601: return "10"
    if vol <= 1655: return "11"
    if vol <= 1919: return "12"
    if vol <= 2045: return "13"
    if vol <= 2189: return "14"
    if vol <= 2405: return "15"
    if vol <= 2621: return "16"
    if vol <= 2837: return "17"
    if vol <= 3053: return "18"
    if vol <= 3269: return "19"
    if vol <= 3485: return "20"
    return "21"

def extract_smart_category(title: str) -> str:
    if not title: return "clothing"
    text = title.lower()
    junk = ["почти готово", "wildberries", "интернет-магазин", "одежда", "v0", "just a moment", "loading"]
    if any(j in text for j in junk) or len(title) < 3:
        return "clothing"
    text = re.sub(r'[^а-яёa-z\s]', ' ', text)
    return " ".join(text.split()[:3])

def parse_wildberries(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    common_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.wildberries.ru/"
    }

    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", headers=common_headers, timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', {}).get('products', [])
            if data:
                title = f"{data[0].get('brand', '')} {data[0].get('name', '')}".strip()
    except: pass

    if not title or "одежда" in title.lower():
        try:
            r_html = crequests.get(url, impersonate="chrome120", headers=common_headers, timeout=5)
            soup = BeautifulSoup(r_html.text, 'html.parser')
            og_title = soup.find('meta', property='og:title')
            title = og_title.get('content') if og_title else soup.title.string
            if title: title = re.sub(r' — купить.*', '', title, flags=re.I).strip()
        except: pass

    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(nm_id)
    host = f"basket-{basket}.wbbasket.ru"
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 10)]
    
    return image_urls, title or "Товар Wildberries"

def process_single_image(idx, url, item_category):
    try:
        resp = crequests.get(url, impersonate="chrome120", timeout=10)
        if resp.status_code != 200:
            logger.warning(f"❌ Фото {idx} недоступно: {resp.status_code}")
            return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # Инфографика
        img_gray = img.convert("L")
        edges = img_gray.filter(ImageFilter.FIND_EDGES)
        edge_density = ImageStat.Stat(edges).mean[0]
        
        # CLIP Scoring
        preview = img.copy()
        preview.thumbnail((336, 336))
        
        # Ослабляем пороги, если мы в режиме "clothing"
        is_fallback = (item_category == "clothing")
        prompt = "fashion clothing item" if is_fallback else f"a professional photo of {item_category}"
        min_score = 15.0 if is_fallback else 25.0
        max_edges = 45 if is_fallback else 35

        score = rate_image_relevance(preview, prompt)
        
        # Логируем для отладки
        logger.info(f"📸 Фото {idx}: Score={score:.1f}, Edges={edge_density:.1f}")

        # Если фото совсем плохое, но это единственное что есть - мы его все равно сохраним, 
        # но пометим как низкоприоритетное
        is_bad = (edge_density > max_edges or score < min_score)
        
        out = BytesIO()
        preview.save(out, format="JPEG", quality=85)
        
        return {
            "key": f"v_{idx}",
            "url": url,
            "data": out.getvalue(),
            "score": score,
            "is_bad": is_bad,
            "idx": idx
        }
    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото {idx}: {e}")
        return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    image_urls, full_title = parse_wildberries(payload.url)
    item_category = extract_smart_category(full_title)
    logger.info(f"🎯 Ищем категорию: {item_category} (Оригинал: {full_title})")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=5) as executor:
        tasks = [loop.run_in_executor(executor, process_single_image, i, url, item_category) 
                 for i, url in enumerate(image_urls)]
        all_results = [r for r in await asyncio.gather(*tasks) if r]

    if not all_results:
        raise HTTPException(400, "Не удалось загрузить ни одного изображения товара")

    # Сначала пробуем хорошие фото
    good_results = [r for r in all_results if not r["is_bad"]]
    
    # Если хороших нет (например, везде инфографика), берем все что есть (Rescue Mode)
    final_selection = good_results if good_results else all_results
    final_selection.sort(key=lambda x: x['score'], reverse=True)

    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for item in final_selection[:6]:
        v_key = item["key"]
        saved_url = save_image(f"t_{temp_id}_{v_key}.jpg", item["data"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}
    
    display_name = full_title[:60] if item_category != "clothing" else "Новая вещь"
    
    return {
        "temp_id": temp_id,
        "suggested_name": display_name,
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
