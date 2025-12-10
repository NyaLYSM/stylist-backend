# routers/import_router.py
from fastapi import APIRouter, HTTPException
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from PIL import Image, UnidentifiedImageError
import io

router = APIRouter()

VALID_EXT = (".jpg", ".jpeg", ".png", ".webp", ".avif")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def is_valid_image_bytes(b: bytes):
    try:
        img = Image.open(io.BytesIO(b))
        img.verify()
        return True, img.size  # (width, height)
    except UnidentifiedImageError:
        return False, (0, 0)
    except Exception:
        return False, (0, 0)


def fetch_image_head(url, timeout=8):
    """Try to fetch headers first, then minimal bytes to validate."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        r.raise_for_status()
    except requests.RequestException:
        return None

    # try to read some bytes (up to 200KB) to validate
    try:
        chunk = r.raw.read(200 * 1024)
    except Exception:
        return None

    valid, size = is_valid_image_bytes(chunk)
    if not valid:
        return None
    return {"url": url, "size": size}


def extract_images(url):
    """Извлекает изображения со страницы, возвращает список candidate dicts"""
    try:
        response = requests.get(url, timeout=10, headers=HEADERS)
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

        if src in seen:
            continue

        # ext check
        if not any(ext in src.lower() for ext in VALID_EXT):
            # still attempt if URL has no ext but may be image -> try later
            pass

        # skip tiny icons / logos
        low = src.lower()
        if any(skip in low for skip in ['logo', 'icon', 'sprite', 'thumb', 'avatar', 'pixel', '1x1']):
            continue

        seen.add(src)
        imgs.append(src)

    # Try to validate & score found images by fetching small chunk
    candidates = []
    for u in imgs:
        info = fetch_image_head(u)
        if info:
            candidates.append(info)

    # If we got none via validation attempt, fallback to raw urls (limited)
    if not candidates:
        for u in imgs[:6]:
            candidates.append({"url": u, "size": (0, 0)})

    # sort by area desc (largest first)
    candidates.sort(key=lambda x: x.get("size", (0, 0))[0] * x.get("size", (0, 0))[1], reverse=True)

    # limit to 6
    return candidates[:6]


@router.post("/fetch")
def fetch_candidates(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(400, "Не указан url")

    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Невалидный URL")

    candidates = extract_images(url)
    if not candidates:
        raise HTTPException(404, "Картинки не найдены")

    # return simple list of {url, width, height}
    resp = []
    for c in candidates:
        w, h = c.get("size", (0, 0))
        resp.append({"url": c["url"], "width": int(w or 0), "height": int(h or 0)})

    return {"success": True, "candidates": resp, "count": len(resp)}
