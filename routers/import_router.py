# routers/import_router.py
from fastapi import APIRouter, HTTPException
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

router = APIRouter()

VALID_EXT = (".jpg", ".jpeg", ".png", ".webp", ".avif")

def extract_images(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        html = response.text
    except requests.RequestException as e:
        raise HTTPException(400, f"Не удалось загрузить страницу: {str(e)}")

    soup = BeautifulSoup(html, "html.parser")
    imgs = []
    seen = set()

    for tag in soup.find_all("img"):
        src = (
            tag.get("src") or 
            tag.get("data-src") or 
            tag.get("data-lazy-src") or
            tag.get("data-original")
        )
        if not src:
            continue
        if not src.startswith("http"):
            src = urljoin(url, src)
        if not any(ext in src.lower() for ext in VALID_EXT):
            continue
        if any(skip in src.lower() for skip in ['logo', 'icon', 'sprite', 'pixel', '1x1']):
            continue
        if src in seen:
            continue
        seen.add(src)
        imgs.append(src)
        if len(imgs) >= 10:
            break

    return imgs[:6]

@router.post("/fetch")
def fetch_candidates(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(400, "Не указан url")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Невалидный URL (должен начинаться с http:// или https://)")
    images = extract_images(url)
    if not images:
        raise HTTPException(404, "Картинки не найдены на этой странице")
    return {"success": True, "candidates": [{"url": img} for img in images], "count": len(images)}
