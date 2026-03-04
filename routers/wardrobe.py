import os, uuid, time, asyncio, re, logging, json
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageFilter, ImageStat
import requests
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as crequests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from .dependencies import get_current_user_id
from pydantic import BaseModel, ConfigDict
from typing import Optional

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Интеграция с CLIP
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client loaded and ready for filtering")
except ImportError:
    logger.warning("⚠️ CLIP module not found. Using dummy relevance.")
    def rate_image_relevance(img, name): return 100.0

router = APIRouter(tags=["Wardrobe"])

# --- Схемы данных ---
class ItemUrlPayload(BaseModel):
    url: str
    name: Optional[str] = "" # Делаем имя необязательным, чтобы избежать 400 ошибки

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

# Временное хранилище для вариантов
VARIANTS_STORAGE = {}

def get_wb_basket(vol: int) -> str:
    """Обновленная логика корзин WB (актуально для артикулов 480млн+)"""
    if 0 <= vol <= 143: return "01"
    elif 144 <= vol <= 287: return "02"
    elif 288 <= vol <= 431: return "03"
    elif 432 <= vol <= 719: return "04"
    elif 720 <= vol <= 1007: return "05"
    elif 1008 <= vol <= 1061: return "06"
    elif 1062 <= vol <= 1115: return "07"
    elif 1116 <= vol <= 1169: return "08"
    elif 1170 <= vol <= 1313: return "09"
    elif 1314 <= vol <= 1601: return "10"
    elif 1602 <= vol <= 1655: return "11"
    elif 1656 <= vol <= 1919: return "12"
    elif 1920 <= vol <= 2045: return "13"
    elif 2046 <= vol <= 2189: return "14"
    elif 2190 <= vol <= 2405: return "15"
    elif 2406 <= vol <= 2621: return "16"
    elif 2622 <= vol <= 2837: return "17"
    elif 2838 <= vol <= 3053: return "18"
    elif 3054 <= vol <= 3269: return "19"
    elif 3270 <= vol <= 3485: return "20"
    elif 3486 <= vol <= 3701: return "21"
    elif 3702 <= vol <= 3917: return "22"
    elif 3918 <= vol <= 4133: return "23"
    elif 4134 <= vol <= 4349: return "24"
    elif 4350 <= vol <= 4565: return "25"
    elif 4566 <= vol <= 4781: return "26"
    elif 4782 <= vol <= 4997: return "27" # Для вашего артикула 489... (vol 4890)
    return "28"

def parse_wildberries(url: str):
    """Парсинг WB: Название + URL картинок"""
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    # 1. Тянем название через API (Brand + Name)
    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", timeout=5)
        if r.status_code == 200:
            products = r.json().get('data', {}).get('products', [])
            if products:
                p = products[0]
                brand = p.get('brand', '')
                p_name = p.get('name', '')
                title = f"{brand} / {p_name}".strip(" / ")
    except Exception as e:
        logger.error(f"WB API error: {e}")

    # 2. Формируем ссылки на фото
    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    
    image_urls = [
        f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" 
        for i in range(1, 11)
    ]
    return image_urls, title or "Вещь Wildberries"

def download_and_process_img(idx, url):
    """Воркер: загрузка + сжатие + фильтрация CLIP"""
    try:
        resp = crequests.get(url, impersonate="chrome120", timeout=10)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # Предварительный анализ: отсекаем таблицы размеров (много мелких деталей/краев)
        gray = img.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_val = ImageStat.Stat(gray).mean[0]
        
        # Сжатие для CLIP и превью
        img_processed = img.copy()
        img_processed.thumbnail((400, 400))
        
        score = rate_image_relevance(img_processed, "clothing photography, model wearing clothes")
        
        # Если это явно инфографика/таблица (edge_val > 45) или не одежда (score < 20)
        if edge_val > 50 or (CLIP_AVAILABLE and score < 20):
            logger.info(f"🗑️ Image {idx} filtered (Edges: {edge_val:.1f}, CLIP: {score:.1f})")
            return None

        out = BytesIO()
        img_processed.save(out, format="JPEG", quality=85)
        
        return {
            "key": f"v_{idx}",
            "original_url": url,
            "preview_bytes": out.getvalue(),
            "score": score
        }
    except Exception as e:
        return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    logger.info(f"🌐 Начинаем обработку: {payload.url}")
    
    if "wildberries" not in payload.url and "wb.ru" not in payload.url:
        raise HTTPException(400, "Поддерживается только Wildberries")

    image_urls, suggested_title = parse_wildberries(payload.url)
    
    # ПАРАЛЛЕЛЬНАЯ ЗАГРУЗКА
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        loop = asyncio.get_event_loop()
        futures = [loop.run_in_executor(executor, download_and_process_img, i, url) for i, url in enumerate(image_urls)]
        downloaded = await asyncio.gather(*futures)
        results = [r for r in downloaded if r]

    if not results:
        # Если все фото отфильтрованы, пробуем взять хотя бы первую картинку без фильтров
        raise HTTPException(400, "Не удалось загрузить фото. Проверьте ссылку.")

    # Сортировка по CLIP (лучшие фото одежды — первые)
    results.sort(key=lambda x: x["score"], reverse=True)

    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for item in results[:6]: 
        v_key = item["key"]
        saved_url = save_image(f"temp_{temp_id}_{v_key}.jpg", item["preview_bytes"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["original_url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}
    
    return {
        "temp_id": temp_id,
        "suggested_name": payload.name if payload.name and payload.name.strip() else suggested_title[:60],
        "variants": previews
    }

@router.post("/select-variant", response_model=ItemResponse)
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(404, "Сессия истекла")
    
    original_url = data["urls"].get(payload.selected_variant)
    resp = crequests.get(original_url, impersonate="chrome120")
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    img.thumbnail((1024, 1024))
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=90)
    final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", out.getvalue())
    
    # Чистка временных файлов
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

@router.delete("/delete")
def delete_item(payload: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item_id = payload.get("item_id")
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if item:
        delete_image(item.image_url)
        db.delete(item); db.commit()
    return {"status": "success"}
