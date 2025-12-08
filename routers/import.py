# routers/import.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from database import db  # твой экземпляр Database
import requests
from some_background_removal_module import remove_background  # опишем позже

router = APIRouter(prefix="/api/import", tags=["import"])

class FetchRequest(BaseModel):
    url: HttpUrl

class AddRequest(BaseModel):
    user_id: int
    image_url: HttpUrl
    name: str
    item_type: str = "unknown"

@router.post("/fetch")
async def import_fetch(req: FetchRequest):
    # тут логика: парсить HTML страницы, вытаскивать картинки
    try:
        resp = requests.get(req.url, timeout=10)
        html = resp.text
        # простая логика: ищем <img> тэги, берём src
        # (в продакшн — лучше использовать bs4 / lxml)
        from re import findall
        imgs = findall(r'<img[^>]+src="([^"]+)"', html)
        candidates = []
        for src in imgs:
            if src.startswith("http"):
                candidates.append({"url": src})
        if not candidates:
            raise ValueError("no images found")
        return {"candidates": candidates}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")

@router.post("/add")
async def import_add(req: AddRequest):
    # скачиваем картинку
    try:
        img_data = requests.get(req.image_url, timeout=10).content
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to download image")

    # вызываем функцию удаления фона
    try:
        output_png = remove_background(img_data)  # возвращает байты PNG без фона
    except Exception as e:
        raise HTTPException(status_code=500, detail="Background removal failed")

    # сохраняем куда-то — например, в папку static/images, имя = uuid.png
    import uuid, os, base64
    fname = f"{uuid.uuid4().hex}.png"
    save_path = os.path.join("static", "images", fname)
    with open(save_path, "wb") as f:
        f.write(output_png)

    url = f"/static/images/{fname}"

    # добавляем вещь в гардероб
    item_id = await db.add_wardrobe_item(
        req.user_id, req.name, req.item_type,
        url, colors=None, description=None
    )

    return {"success": True, "item": {"id": item_id, "image": url}}
