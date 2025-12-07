import requests
from fastapi import APIRouter, HTTPException, Depends
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from database import get_db
from sqlalchemy.orm import Session

from models import WardrobeItem
from datetime import datetime

router = APIRouter(prefix="/import", tags=["import"])


# --------------------------
#  HTML downloader
# --------------------------
def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(400, f"Cannot fetch page: {resp.status_code}")
    return resp.text


# --------------------------
#  Extract image candidates
# --------------------------
def extract_images(url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")

    candidates = []

    # 1) og:image
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        candidates.append({
            "url": urljoin(url, og["content"]),
            "source": "og"
        })

    # 2) all <img>
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        img_url = urljoin(url, src)
        candidates.append({
            "url": img_url,
            "source": "img"
        })

    # Убираем дубликаты
    seen = set()
    uniq = []
    for c in candidates:
        if c["url"] not in seen:
            uniq.append(c)
            seen.add(c["url"])

    return uniq[:12]   # максимум 12 картинок (достаточно)


# --------------------------
#  API: Find candidates
# --------------------------
@router.post("/fetch")
def fetch_from_url(data: dict):
    url = data.get("url")
    if not url:
        raise HTTPException(400, "No URL provided")

    html = fetch_html(url)
    candidates = extract_images(url, html)

    return {"count": len(candidates), "candidates": candidates}


# --------------------------
#  Background removal (stub)
# --------------------------
def remove_background_stub(image_bytes: bytes) -> bytes:
    """
    Здесь может быть интеграция:
    - ClipDrop
    - Remove.bg
    - Baseten
    Сейчас: возвращает оригинал без изменений.
    """
    return image_bytes


# --------------------------
#  API: Final Add
# --------------------------
@router.post("/add")
def add_from_url(data: dict, db: Session = Depends(get_db)):
    user_id = data.get("user_id")
    image_url = data.get("image_url")
    name = data.get("name", "Одежда")
    item_type = data.get("item_type", "other")

    if not user_id or not image_url:
        raise HTTPException(400, "Missing user_id or image_url")

    # Скачать изображение
    resp = requests.get(image_url, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(400, "Cannot download image")

    original_bytes = resp.content

    # Удаление фона (пока заглушка)
    clean_bytes = remove_background_stub(original_bytes)

    # Сохраняем изображение в CDN/free-host (или прямо URL)
    # Пока — просто хранить оригинальный URL
    # (можно улучшить)
    saved_url = image_url

    # Добавляем в базу
    item = WardrobeItem(
        user_id=user_id,
        item_name=name,
        item_type=item_type,
        photo_url=saved_url,
        created_at=datetime.utcnow()
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return {"success": True, "item_id": item.id}
