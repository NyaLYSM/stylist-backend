import os, uuid, time, asyncio, re, logging, json
from datetime import datetime
from io import BytesIO
from PIL import Image
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
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Попытка импорта CLIP
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
    logger.info("✅ CLIP client ready for filtering")
except ImportError:
    def rate_image_relevance(img, name): return 100.0

router = APIRouter(tags=["Wardrobe"])

class ItemUrlPayload(BaseModel):
    name: str
    url: str

class SelectVariantPayload(BaseModel):
    temp_id: str
    selected_variant: str
    name: str

VARIANTS_STORAGE = {}

def get_wb_basket(vol: int) -> str:
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
    else: return "16"

def parse_wildberries(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    # 1. Пытаемся достать нормальное название через API
    title = ""
    try:
        # Пробуем API карточки (более надежное для названия)
        info_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(info_url, impersonate="chrome120", timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', {}).get('products', [])
            if data:
                p = data[0]
                brand = p.get('brand', '')
                product_name = p.get('name', '')
                title = f"{brand} / {product_name}".strip(" / ")
    except Exception as e:
        logger.warning(f"WB API fail: {e}")

    # 2. Если API подвело, идем в HTML за <h1>
    if not title or title.lower() == "одежда":
        try:
            r_html = crequests.get(url, impersonate="chrome120", timeout=5)
            soup = BeautifulSoup(r_html.text, 'html.parser')
            h1 = soup.find('h1')
            if h1: title = h1.get_text(strip=True)
        except: pass

    if not title: title = "Вещь из Wildberries"

    # 3. Формируем ссылки на картинки
    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    
    # Берем до 10 фото для анализа
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 11)]
    return image_urls, title

def process_single_image(idx, url, target_name):
    """Функция для параллельного выполнения: загрузка + сжатие + CLIP"""
    try:
        resp = requests.get(url, timeout=7)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # Сжатие до 336x336 для скорости и CLIP
        img_preview = img.copy()
        img_preview.thumbnail((336, 336))
        
        # Фильтрация мусора через CLIP
        score = rate_image_relevance(img_preview, "clothing, fashion item")
        if score < 25: # Порог отсечения таблиц размеров и текста
            logger.info(f"🗑️ Img {idx} rejected (Score {score:.1f})")
            return None

        # Сохранение временного превью
        out = BytesIO()
        img_preview.save(out, format="JPEG", quality=80)
        return {
            "id": f"v_{idx}",
            "full_url": url,
            "preview_bytes": out.getvalue(),
            "score": score
        }
    except Exception as e:
        return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    if "wildberries" in payload.url or "wb.ru" in payload.url:
        image_urls, suggested_title = parse_wildberries(payload.url)
    else:
        raise HTTPException(400, "Поддерживается только Wildberries")

    if not image_urls:
        raise HTTPException(400, "Изображения не найдены")

    # Использование названия от пользователя, если оно введено, иначе - найденное
    final_title = payload.name if payload.name.strip() else suggested_title

    # Параллельная обработка картинок
    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_single_image, i, url, "clothing") for i, url in enumerate(image_urls)]
        for f in futures:
            res = f.result()
            if res: results.append(res)

    if not results:
        raise HTTPException(400, "Не найдено подходящих фото одежды (возможно, только таблицы размеров)")

    # Сортируем по релевантности CLIP
    results.sort(key=lambda x: x["score"], reverse=True)
    
    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for res in results[:6]: # Берем топ-6 лучших фото
        v_key = res["id"]
        saved_url = save_image(f"temp_{temp_id}_{v_key}.jpg", res["preview_bytes"])
        previews[v_key] = saved_url
        full_urls[v_key] = res["full_url"]

    VARIANTS_STORAGE[temp_id] = {
        "urls": full_urls, 
        "previews": previews, 
        "user_id": user_id
    }

    return {
        "temp_id": temp_id, 
        "suggested_name": final_title[:60], 
        "variants": previews, 
        "total_images": len(previews)
    }

@router.post("/select-variant")
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(404, "Сессия истекла или не найдена")
    
    original_url = data["urls"].get(payload.selected_variant)
    if not original_url:
        raise HTTPException(400, "Вариант не найден")

    # Скачиваем оригинал в лучшем качестве
    resp = requests.get(original_url, timeout=15)
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    
    # Финальное сохранение (можно чуть больше размер)
    img.thumbnail((1024, 1024))
    out = BytesIO()
    img.save(out, format="JPEG", quality=90)
    
    final_url = save_image(f"item_{uuid.uuid4().hex}.jpg", out.getvalue())
    
    # Чистим временные файлы
    for p in data["previews"].values():
        try: delete_image(p)
        except: pass
    del VARIANTS_STORAGE[payload.temp_id]

    item = WardrobeItem(
        user_id=user_id, 
        name=payload.name, 
        image_url=final_url, 
        item_type="marketplace",
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.get("/items")
def get_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.created_at.desc()).all()

@router.delete("/delete")
def delete_item(payload: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item_id = payload.get("item_id")
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if item:
        delete_image(item.image_url)
        db.delete(item)
        db.commit()
    return {"status": "ok"}
