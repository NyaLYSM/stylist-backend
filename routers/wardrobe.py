# routers/wardrobe.py
import io
import filetype
import requests
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem, User
from typing import Optional
from datetime import datetime
from clip_utils import load_image, clip_is_clothing, clip_match_title
from fastapi import HTTPException

router = APIRouter()

# Limits
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png", "image/webp", "image/avif")
ALLOWED_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# Простая валидация названий (белый список категорий + черный список слов)
WHITELIST_KEYWORDS = {
    "футболка","рубашка","платье","джинсы","куртка","пальто","кофта","кардиган",
    "свитер","штаны","шорты","юбка","блузка","костюм","пиджак","кроссовки",
    "ботинки","туфли","сандалии","сумка","рюкзак","шапка","палки","палантин",
    "толстовка","боди","топ","жилет","поло","пижама","нижнее белье","трусики",
    "майка","плащ"
}
BLACKLIST_WORDS = {"нелегальн","запрет","porn","sex","нелегаль"}

def upload_to_telegraph(img_bytes: bytes, filename: str) -> str:
    files = {"file": (filename, img_bytes)}
    try:
        r = requests.post("https://telegra.ph/upload", files=files, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or "src" not in data[0]:
            raise RuntimeError("Bad response from telegra.ph")
        return "https://telegra.ph" + data[0]["src"]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Telegraph upload failed: {e}")

def validate_name(name: str):
    if not name:
        raise HTTPException(400, "Название не может быть пустым")
    n = name.lower()
    if any(b in n for b in BLACKLIST_WORDS):
        raise HTTPException(400, "Название содержит недопустимые слова")
    # по возможности — проверить наличие хотя бы одного слова из белого списка
    if not any(k in n for k in WHITELIST_KEYWORDS):
        # не критично — можно разрешить, но лучше предупредить; тут — просто запретим слишком абстрактные
        if len(n) < 3 or len(n.split()) > 6:
            raise HTTPException(400, "Название выглядит некорректно — укажите тип вещи (например: 'Белая футболка')")

def fetch_image_bytes(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
    try:
        r = requests.get(url, timeout=15, headers=headers, stream=True)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(400, f"Не удалось скачать изображение: {e}")

    # Read with limit
    buf = io.BytesIO()
    total = 0
    for chunk in r.iter_content(8192):
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Файл слишком большой (более 5 МБ)")
        buf.write(chunk)
    return buf.getvalue()

def detect_image_type(b: bytes) -> Optional[str]:
    """
    Определяет тип файла (расширение) по байтам.
    Заменено imghdr (удален в Python 3.13) на filetype.
    """
    # Используем filetype для определения типа по байтам
    kind = filetype.guess(b)
    if kind:
        # filetype возвращает 'image/jpeg', 'image/png' и т.д.
        # для обратной совместимости вернем только расширение (без точки)
        return kind.extension
    return None

# ---------- List ----------
@router.get("/list")
def wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter_by(user_id=user_id).order_by(WardrobeItem.id.desc()).all()
    return {"items": items}

# ---------- Add (JSON) ----------
@router.post("/add")
def add_item(payload: dict, db: Session = Depends(get_db)):
    """
    payload: { user_id, name, image_url, item_type }
    If image_url points to external host (not telegra.ph) backend will fetch and reupload to Telegraph.
    """
    user_id = payload.get("user_id")
    name = payload.get("name", "").strip()
    image_url = payload.get("image_url", "").strip()
    item_type = payload.get("item_type", "unknown")

    if not user_id or not name or not image_url:
        raise HTTPException(400, "Нужны user_id, name и image_url")

    validate_name(name)

    # If image is already telegraph, keep it
    if image_url.startswith("https://telegra.ph/") or "telegra.ph/file" in image_url:
        final_url = image_url
    else:
        # try to download image and reupload to Telegraph
        img_bytes = fetch_image_bytes(image_url)
        # minimal check
        img_t = detect_image_type(img_bytes)
        if not img_t:
            raise HTTPException(400, "Не удалось распознать формат изображения")
        fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{img_t}"
        final_url = upload_to_telegraph(img_bytes, fname)

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type=item_type,
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": item}

    # 1) Загружаем изображение (CLIP)
    img = load_image(payload["image_url"])
    if img is None:
        raise HTTPException(400, "Не удалось загрузить изображение — недоступный URL.")

    # 2) Проверяем что это действительно одежда
    is_cloth, detected = clip_is_clothing(img)
    if not is_cloth:
        raise HTTPException(
            400,
            f"Похоже это не одежда. Определено как: {detected}"
        )

    # 3) Проверяем соответствие названия содержимому
    if not clip_match_title(img, payload["name"]):
        raise HTTPException(
            400,
            "Название не совпадает с тем, что на фото. "
            "Попробуйте назвать вещь точнее."
        )

# ---------- Upload file (multipart) ----------
@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Basic checks
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Тип файла не поддерживается")
    # Read bytes with limit
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл слишком большой (макс 5 МБ)")
    # detect type
    img_t = detect_image_type(data)
    if not img_t:
        raise HTTPException(400, "Не изображение")

    validate_name(name)

    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
    tele_url = upload_to_telegraph(data, fname)

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="upload",
        image_url=tele_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": item}

# ---------- Delete ----------
@router.delete("/{item_id}")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    item = db.query(WardrobeItem).filter_by(id=item_id, user_id=user_id).first()
    if not item:
        raise HTTPException(404, "Вещь не найдена")
    db.delete(item)
    db.commit()
    return {"status": "ok", "deleted_id": item_id}
