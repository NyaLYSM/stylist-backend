import os, uuid, time, asyncio, re, logging, json
from datetime import datetime
from io import BytesIO
from PIL import Image
import requests
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as crequests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict

from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from .dependencies import get_current_user_id

logger = logging.getLogger(__name__)

# --- Интеграция с CLIP ---
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client loaded")
except ImportError:
    def rate_image_relevance(img, name): return 100.0

router = APIRouter(tags=["Wardrobe"])

# --- Схемы данных ---
class ItemUrlPayload(BaseModel):
    name: str
    url: str

class SelectVariantPayload(BaseModel):
    temp_id: str
    selected_variant: str
    name: str

class ItemResponse(BaseModel):
    id: int
    name: str
    image_url: str
    item_type: str
    created_at: datetime
    # Исправление предупреждения Pydantic V2 из логов
    model_config = ConfigDict(from_attributes=True)

VARIANTS_STORAGE = {}

def get_wb_basket(vol: int) -> str:
    """Определение корзины WB (актуально на 2024-2025)"""
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

def parse_wildberries(url: str):
    """Парсинг WB с улучшенным извлечением заголовка"""
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    try:
        # Прямой запрос к API карточки для получения бренда и названия
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", timeout=5)
        if r.status_code == 200:
            p_data = r.json().get('data', {}).get('products', [])
            if p_data:
                p = p_data[0]
                title = f"{p.get('brand', '')} {p.get('name', '')}".strip()
    except Exception as e:
        logger.warning(f"WB API error: {e}")

    if not title:
        title = "Вещь из Wildberries"

    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    
    # Генерируем ссылки на первые 8 фото
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 9)]
    return image_urls, title

def download_and_process_img(idx, url):
    """Загрузка, проверка CLIP и подготовка превью"""
    try:
        # Используем curl_cffi для обхода возможных блокировок на CDN
        resp = crequests.get(url, impersonate="chrome120", timeout=10)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # CLIP проверка: снижаем порог до 15, чтобы не резать реальные фото
        score = rate_image_relevance(img, "clothing, fashion item on plain background")
        if score < 15: 
            return None

        # Создаем компактное превью
        preview = img.copy()
        preview.thumbnail((400, 400))
        
        out = BytesIO()
        preview.save(out, format="JPEG", quality=80)
        
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
    if "wildberries" not in payload.url and "wb.ru" not in payload.url:
        raise HTTPException(400, "На данный момент поддерживается только Wildberries")

    image_urls, suggested_title = parse_wildberries(payload.url)
    if not image_urls:
        raise HTTPException(400, "Не удалось получить доступ к изображениям WB")

    final_name = payload.name if payload.name.strip() else suggested_title

    results = []
    # Используем ThreadPool для ускорения загрузки пачки фото
    with ThreadPoolExecutor(max_workers=5) as executor:
        loop = asyncio.get_event_loop()
        futures = [loop.run_in_executor(executor, download_and_process_img, i, url) for i, url in enumerate(image_urls)]
        downloaded = await asyncio.gather(*futures)
        results = [r for r in downloaded if r]

    if not results:
        # Если CLIP всё отфильтровал, пробуем взять хотя бы первое фото без фильтра
        raise HTTPException(400, "Не удалось подобрать качественные фото товара")

    results.sort(key=lambda x: x["score"], reverse=True)

    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for item in results[:6]:
        v_key = item["key"]
        # Сохраняем временное превью
        saved_url = save_image(f"prev_{temp_id}_{v_key}.jpg", item["preview_bytes"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["original_url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}

    return {
        "temp_id": temp_id,
        "suggested_name": final_name[:70],
        "variants": previews,
        "total_images": len(previews)
    }

@router.post("/select-variant", response_model=ItemResponse)
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(408, "Сессия выбора истекла, попробуйте снова")
    
    original_url = data["urls"].get(payload.selected_variant)
    if not original_url:
        raise HTTPException(400, "Выбранный вариант не найден")
    
    try:
        resp = crequests.get(original_url, impersonate="chrome120", timeout=15)
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        img.thumbnail((1024, 1024))
        
        out = BytesIO()
        img.save(out, format="JPEG", quality=90)
        
        final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", out.getvalue())
        
        # Удаляем временные превью
        for p_url in data["previews"].values():
            try: delete_image(p_url)
            except: pass
        del VARIANTS_STORAGE[payload.temp_id]

        new_item = WardrobeItem(
            user_id=user_id,
            name=payload.name,
            image_url=final_url,
            item_type="marketplace",
            created_at=datetime.utcnow()
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return new_item
    except Exception as e:
        logger.error(f"Select variant failed: {e}")
        raise HTTPException(500, "Ошибка при сохранении выбранного фото")

@router.get("/items", response_model=list[ItemResponse])
def get_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.created_at.desc()).all()

@router.delete("/delete")
def delete_item(item_id: int = Query(...), db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item:
        raise HTTPException(404, "Вещь не найдена")
    
    delete_image(item.image_url)
    db.delete(item)
    db.commit()
    return {"status": "ok"}
