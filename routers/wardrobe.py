# routers/wardrobe.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem, User
from utils.telegraph import upload_bytes_to_telegraph
import requests
from typing import Optional

router = APIRouter()


# ---- Tiny name moderation/validation ----
CLOTHING_KEYWORDS = {
    "футболка","рубашка","худи","толстовка","свитшот","пальто","куртка","верхняя одежда",
    "брюки","джинсы","шорты","юбка","платье","топ","майка","рубаха","пиджак",
    "кеды","кроссовки","ботинки","туфли","сандалии","сланцы","сапоги",
    "пояс","шапка","шарф","перчатки","носок","колготки"
    # Добавь сюда свои слова — коллекция расширяема
}

def validate_name(name: str) -> bool:
    n = name.strip().lower()
    if len(n) < 2 or len(n) > 120:
        return False
    # простая проверка: присутствует хотя бы одно ключевое слово одежды
    for kw in CLOTHING_KEYWORDS:
        if kw in n:
            return True
    # если не найдено ключевых слов — отвергнем, т.к. вероятно не одежда
    return False


# ----- Helpers -----
def _download_image(url: str, max_bytes: int = 5 * 1024 * 1024) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; StylistBot/1.0)"
    }
    with requests.get(url, stream=True, timeout=12, headers=headers) as r:
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ValueError("URL не указывает на изображение")
        total = 0
        chunks = []
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Размер изображения превышает 5 МБ")
                chunks.append(chunk)
        return b"".join(chunks)


# ---------------------------
# 1) Add from URL (JSON body)
# ---------------------------
@router.post("/add_from_url")
def add_from_url(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { user_id: int, name: str, url: str }
    """
    user_id = payload.get("user_id")
    name = (payload.get("name") or "").strip()
    url = payload.get("url") or ""

    if not user_id or not name or not url:
        raise HTTPException(status_code=400, detail="user_id, name, url required")

    # name validation
    if not validate_name(name):
        raise HTTPException(status_code=400, detail="Название выглядит не как одежда, уточните (пример: 'Белая футболка')")

    # Try to download image
    try:
        img_bytes = _download_image(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить изображение: {str(e)}")

    # Upload to Telegraph
    ok, res = upload_bytes_to_telegraph(img_bytes, "imported.jpg")
    if not ok:
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке изображения: {res}")

    image_url = res

    # Persist: ensure user exists (create if not)
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        # create minimal user row
        user = User(tg_id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    item = WardrobeItem(
        user_id=user.tg_id,
        name=name,
        item_type="import",
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"success": True, "item": {
        "id": item.id,
        "name": item.name,
        "image_url": item.image_url,
        "item_type": item.item_type
    }}


# ---------------------------
# 2) Add from file (form multipart)
# ---------------------------
@router.post("/add_from_file")
def add_from_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    multipart/form-data:
      - user_id
      - name
      - file (image)
    """
    # Basic checks
    if not validate_name(name):
        raise HTTPException(status_code=400, detail="Название выглядит не как одежда, уточните (пример: 'Белая футболка')")

    # limit size to 5MB
    MAX_BYTES = 5 * 1024 * 1024
    if file.content_type is None or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Файл должен быть изображением")

    contents = file.file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Пустой файл")
    if len(contents) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Размер файла превышает 5 МБ")

    # Upload to Telegraph
    ok, res = upload_bytes_to_telegraph(contents, file.filename or "upload.jpg")
    if not ok:
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке изображения: {res}")

    image_url = res

    # Ensure user exists
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        user = User(tg_id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    item = WardrobeItem(
        user_id=user.tg_id,
        name=name,
        item_type="file",
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"success": True, "item": {
        "id": item.id,
        "name": item.name,
        "image_url": item.image_url,
        "item_type": item.item_type
    }}


# Keep existing simple list method (compatibility)
@router.get("/list")
def wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter_by(user_id=user_id).order_by(WardrobeItem.id.desc()).all()
    # SQLAlchemy objects are returned; convert to simple dicts
    out = []
    for it in items:
        out.append({
            "id": it.id,
            "name": it.name,
            "item_type": it.item_type,
            "image_url": it.image_url,
            "created_at": it.created_at.isoformat() if it.created_at else None
        })
    return {"items": out}
