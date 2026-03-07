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

# CLIP Integration
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
except ImportError:
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

def get_wb_basket_v2(nm_id: int) -> str:
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
    if vol <= 3701: return "21"
    if vol <= 3917: return "22"
    if vol <= 4133: return "23"
    if vol <= 4349: return "24"
    if vol <= 4565: return "25"
    if vol <= 4781: return "26"
    if vol <= 4997: return "27"
    if vol <= 5213: return "28"
    if vol <= 5429: return "29"
    return "30"

async def find_working_basket(nm_id: int):
    vol, part = nm_id // 100000, nm_id // 1000
    initial_basket = get_wb_basket_v2(nm_id)
    baskets_to_try = [initial_basket] + [f"{i:02d}" for i in range(1, 31) if f"{i:02d}" != initial_basket]
    
    for b in baskets_to_try:
        test_url = f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
        try:
            r = crequests.head(test_url, impersonate="chrome120", timeout=2)
            if r.status_code == 200: return b
        except: continue
    return initial_basket

def clean_wb_title(title: str) -> str:
    """Очищает название от мусора WB, оставляя суть"""
    if not title: return ""
    # Убираем стандартные приписки
    junk_patterns = [
        r"почти готово\.\.\.", r"wildberries", r"интернет-магазин", 
        r"бесплатная доставка", r"одежда", r"v0", r"обувь"
    ]
    res = title.lower()
    for pattern in junk_patterns:
        res = re.sub(pattern, "", res)
    
    # Очищаем от лишних знаков и пробелов
    res = re.sub(r'[^\w\sа-яё-]', ' ', res)
    words = res.split()
    # Возвращаем капитализированную строку (например, "Брюки Палаццо")
    return " ".join(words).strip().capitalize()

async def parse_wildberries_v3(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Новый товар"
    nm_id = int(match.group(1))
    
    title = ""
    # Список регионов для обхода блокировок API
    dests = ["-1257786", "-1255800", "-121393"]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
    }

    # Пытаемся получить имя через несколько API
    for d in dests:
        try:
            api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest={d}&nm={nm_id}"
            r = crequests.get(api_url, impersonate="chrome120", headers=headers, timeout=5)
            if r.status_code == 200:
                p_list = r.json().get('data', {}).get('products', [])
                if p_list:
                    p = p_list[0]
                    brand = p.get('brand', '')
                    name = p.get('name', '')
                    title = f"{brand} {name}".strip()
                    if title: break
        except: continue

    # Очищаем полученное название
    final_title = clean_wb_title(title) or "Товар Wildberries"
    logger.info(f"🔎 Распознано название: {final_title}")

    # Поиск картинок
    basket = await find_working_basket(nm_id)
    vol, part = nm_id // 100000, nm_id // 1000
    host = f"basket-{basket}.wbbasket.ru"
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 10)]
    
    return image_urls, final_title

def process_single_image(idx, url, item_category):
    try:
        resp = crequests.get(url, impersonate="chrome120", timeout=10)
        if resp.status_code != 200: return None
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        edge_density = ImageStat.Stat(img.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
        preview = img.copy()
        preview.thumbnail((336, 336))
        
        # Если категория пустая, ищем просто одежду
        tag = item_category if len(item_category) > 3 else "fashion item"
        score = rate_image_relevance(preview, tag)
        
        is_bad = (edge_density > 45 or score < 12.0)
        out = BytesIO()
        preview.save(out, format="JPEG", quality=85)
        return {"key": f"v_{idx}", "url": url, "data": out.getvalue(), "score": score, "is_bad": is_bad}
    except: return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    image_urls, full_title = await parse_wildberries_v3(payload.url)
    
    # Категория для нейронки (короткая)
    ml_category = " ".join(full_title.split()[:2])
    
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=5) as executor:
        tasks = [loop.run_in_executor(executor, process_single_image, i, url, ml_category) for i, url in enumerate(image_urls)]
        all_results = [r for r in await asyncio.gather(*tasks) if r]

    if not all_results:
        raise HTTPException(400, "Не удалось получить данные о товаре")

    good_results = [r for r in all_results if not r["is_bad"]]
    final_selection = good_results if good_results else all_results
    final_selection.sort(key=lambda x: x['score'], reverse=True)

    temp_id = uuid.uuid4().hex
    previews, full_urls = {}, {}

    for item in final_selection[:6]:
        v_key = item["key"]
        saved_url = save_image(f"t_{temp_id}_{v_key}.jpg", item["data"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}
    
    return {
        "temp_id": temp_id, 
        "suggested_name": full_title, 
        "variants": previews
    }

@router.post("/select-variant")
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id: raise HTTPException(404, "Session expired")
    
    r = crequests.get(data["urls"].get(payload.selected_variant), impersonate="chrome120")
    final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", r.content)
    
    # Удаляем временные превью
    for p_url in data["previews"].values():
        try: delete_image(p_url)
        except: pass
    del VARIANTS_STORAGE[payload.temp_id]

    item = WardrobeItem(user_id=user_id, name=payload.name, image_url=final_url, item_type="marketplace", created_at=datetime.utcnow())
    db.add(item); db.commit(); db.refresh(item)
    return item

@router.get("/items")
def get_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.id.desc()).all()
