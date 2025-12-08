from fastapi import APIRouter, HTTPException
import requests
from bs4 import BeautifulSoup

router = APIRouter()

VALID_EXT = (".jpg", ".jpeg", ".png", ".webp")

def extract_images(url):
    try:
        html = requests.get(url, timeout=7).text
    except:
        raise HTTPException(400, "Не удалось загрузить страницу")

    soup = BeautifulSoup(html, "html.parser")
    imgs = []

    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src")
        if not src:
            continue

        if not src.startswith("http"):
            continue

        if any(ext in src.lower() for ext in VALID_EXT):
            imgs.append(src)

    return imgs[:6]  # максимум 6 лучших кандидатов

@router.post("/fetch")
def fetch_candidates(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(400, "Нет url")

    images = extract_images(url)

    if not images:
        raise HTTPException(404, "Картинки не найдены")

    return {"candidates": [{"url": x} for x in images]}
