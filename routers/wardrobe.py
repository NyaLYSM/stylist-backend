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

# Интеграция с CLIP
CLIP_AVAILABLE = False
try:
    from utils.clip_client import rate_image_relevance
    CLIP_AVAILABLE = True
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
    """Динамическое определение корзины WB для новых артикулов"""
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
    else: return "21" # Фолбек для очень высоких ID

def parse_wildberries(url: str):
    match = re.search(r'catalog/(\d+)', url)
    if not match: return [], "Товар WB"
    nm_id = int(match.group(1))
    
    title = ""
    # 1. Тянем метаданные через API (Бренд + Название)
    try:
        api_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&nm={nm_id}"
        r = crequests.get(api_url, impersonate="chrome120", timeout=5)
        if r.status_code == 200:
            p_data = r.json().get('data', {}).get('products', [])
            if p_data:
                p = p_data[0]
                brand = p.get('brand', '')
                p_name = p.get('name', '')
                title = f"{brand} {p_name}".strip()
    except Exception as e:
        logger.warning(f"WB API Title failed: {e}")

    # 2. Если API молчит, парсим HTML глубоко
    if not title or title.lower() == "одежда":
        try:
            r_html = crequests.get(url, impersonate="chrome120", timeout=5)
            soup = BeautifulSoup(r_html.text, 'html.parser')
            # Ищем заголовок в разных тегах, которые использует WB
            h1 = soup.find('h1', class_='product-page__title') or soup.find('h1')
            if h1: title = h1.get_text(strip=True)
        except: pass

    if not title: title = "Вещь из Wildberries"

    # 3. Сборка URL картинок
    vol = nm_id // 100000
    part = nm_id // 1000
    basket = get_wb_basket(vol)
    host = f"basket-{basket}.wbbasket.ru"
    
    # Собираем до 10 фото для выбора лучших
    image_urls = [f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/{i}.webp" for i in range(1, 11)]
    return image_urls, title

def download_and_process_img(idx, url):
    """Параллельный воркер: загрузка + сжатие 336x336 + CLIP"""
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200: return None
        
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        
        # Сразу сжимаем до 336x336 для превью и CLIP
        img.thumbnail((336, 336))
        
        # Проверка CLIP на наличие одежды (исключаем текст и таблицы)
        score = rate_image_relevance(img, "clothing photography, high quality fashion")
        
        if score < 25: # Порог отсева мусора
            logger.info(f"🚫 Img {idx} rejected (Score: {score:.1f})")
            return None

        out = BytesIO()
        img.save(out, format="JPEG", quality=85)
        
        return {
            "key": f"v_{idx}",
            "original_url": url,
            "preview_bytes": out.getvalue(),
            "score": score
        }
    except: return None

@router.post("/add-marketplace-with-variants")
async def add_marketplace_with_variants(payload: ItemUrlPayload, user_id: int = Depends(get_current_user_id)):
    if "wildberries" not in payload.url and "wb.ru" not in payload.url:
        raise HTTPException(400, "Поддерживается только Wildberries")

    image_urls, suggested_title = parse_wildberries(payload.url)
    if not image_urls:
        raise HTTPException(400, "Не удалось найти изображения товара")

    # Название от пользователя или распарсенное
    final_name = payload.name if payload.name.strip() else suggested_title

    # ПАРАЛЛЕЛЬНАЯ ЗАГРУЗКА
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(download_and_process_img, i, url) for i, url in enumerate(image_urls)]
        for f in futures:
            res = f.result()
            if res: results.append(res)

    if not results:
        raise HTTPException(400, "Не найдено подходящих фото (возможно, только таблицы размеров)")

    # Сортируем: лучшие по мнению CLIP — вперед
    results.sort(key=lambda x: x["score"], reverse=True)

    temp_id = uuid.uuid4().hex
    previews = {}
    full_urls = {}

    for item in results[:6]: # Показываем только топ-6
        v_key = item["key"]
        saved_url = save_image(f"temp_{temp_id}_{v_key}.jpg", item["preview_bytes"])
        previews[v_key] = saved_url
        full_urls[v_key] = item["original_url"]

    VARIANTS_STORAGE[temp_id] = {"urls": full_urls, "previews": previews, "user_id": user_id}

    return {
        "temp_id": temp_id,
        "suggested_name": final_name[:70],
        "variants": previews,
        "total_images": len(previews)
    }

@router.post("/select-variant")
async def select_variant(payload: SelectVariantPayload, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    data = VARIANTS_STORAGE.get(payload.temp_id)
    if not data or data["user_id"] != user_id:
        raise HTTPException(404, "Сессия устарела")
    
    original_url = data["urls"].get(payload.selected_variant)
    
    # Скачиваем оригинал для финального сохранения
    resp = requests.get(original_url, timeout=15)
    img = Image.open(BytesIO(resp.content)).convert("RGB")
    img.thumbnail((1024, 1024)) # Финальный размер в гардеробе
    
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
        item_type="marketplace"
    )
    db.add(item); db.commit(); db.refresh(item)
    return item

@router.get("/items")
def get_items(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).order_by(WardrobeItem.id.desc()).all()

@router.delete("/delete")
def delete_item(payload: dict, db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    item_id = payload.get("item_id")
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if item:
        delete_image(item.image_url)
        db.delete(item); db.commit()
    return {"status": "ok"}
