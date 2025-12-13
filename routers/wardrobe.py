# routers/wardrobe.py
import io
import requests
import filetype
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session

from database import get_db
from models import WardrobeItem

from utils.clip_helper import clip_check

router = APIRouter()

# ================== LIMITS ==================
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png", "image/webp", "image/avif")

# ================== BLACKLIST ==================
BLACKLIST_WORDS = {
    "porn", "sex", "xxx", "nsfw", "нелегаль", "запрет"
}

# ================== HUGE WHITELIST ==================
WHITELIST_KEYWORDS = {
    # ---------- RU ----------
    "футболка","лонгслив","рубашка","поло","майка","топ","кроп","блузка",
    "платье","сарафан","комбинация",
    "джинсы","брюки","штаны","чиносы","леггинсы","лосины",
    "шорты","бермуды",
    "юбка","мини","миди","макси",
    "свитер","джемпер","кофта","кардиган","худи","толстовка","свитшот",
    "куртка","пальто","пуховик","плащ","тренч","бомбер","ветровка",
    "пиджак","жакет","костюм","жилет",
    "комбинезон","оверолл",
    "кроссовки","кеды","ботинки","туфли","лоферы","мокасины","сандалии",
    "шлепки","балетки","сапоги","угги",
    "шапка","кепка","панама","берет","шарф","палантин","перчатки",
    "ремень","пояс","сумка","рюкзак","клатч","кошелек",
    "белье","бюстгальтер","трусы","боксеры","пижама","халат",
    "носки","гольфы","колготки",

    # ---------- EN ----------
    "tshirt","t-shirt","shirt","blouse","top","crop",
    "dress","gown","sundress",
    "jeans","pants","trousers","leggings","shorts",
    "skirt",
    "sweater","jumper","hoodie","cardigan","sweatshirt",
    "jacket","coat","parka","bomber","trench",
    "blazer","suit","vest",
    "jumpsuit","overall",
    "sneakers","trainers","shoes","boots","sandals","slippers",
    "hat","cap","beanie","scarf","gloves",
    "belt","bag","backpack","clutch",
    "underwear","bra","briefs","boxers","pajamas",
    "socks","tights"
}

# ================== HELPERS ==================
def validate_name(name: str):
    if not name:
        raise HTTPException(400, "Название не может быть пустым")

    n = name.lower()

    if any(b in n for b in BLACKLIST_WORDS):
        raise HTTPException(400, "Название содержит запрещённые слова")

    if not any(k in n for k in WHITELIST_KEYWORDS):
        if len(n) < 3 or len(n.split()) > 6:
            raise HTTPException(
                400,
                "Название слишком абстрактное. Укажите тип вещи (например: 'Белая футболка')"
            )

def detect_image_type(b: bytes) -> Optional[str]:
    kind = filetype.guess(b)
    return kind.extension if kind else None

def fetch_image_bytes(url: str) -> bytes:
    try:
        r = requests.get(url, timeout=15, stream=True)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(400, f"Не удалось скачать изображение: {e}")

    buf = io.BytesIO()
    total = 0
    for chunk in r.iter_content(8192):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Файл больше 5 МБ")
        buf.write(chunk)
    return buf.getvalue()

def upload_to_telegraph(img_bytes: bytes, filename: str) -> str:
    try:
        r = requests.post(
            "https://telegra.ph/upload",
            files={"file": (filename, img_bytes)},
            timeout=30
        )
        r.raise_for_status()
        return "https://telegra.ph" + r.json()[0]["src"]
    except Exception as e:
        raise HTTPException(502, f"Telegraph upload failed: {e}")

# ================== ROUTES ==================
@router.post("/add")
def add_item(payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("user_id")
    name = payload.get("name", "").strip()
    image_url = payload.get("image_url", "").strip()

    if not user_id or not name or not image_url:
        raise HTTPException(400, "Нужны user_id, name и image_url")

    validate_name(name)

    # --- IMAGE ---
    if image_url.startswith("https://telegra.ph/"):
        final_url = image_url
    else:
        img_bytes = fetch_image_bytes(image_url)
        ext = detect_image_type(img_bytes)
        if not ext:
            raise HTTPException(400, "Не удалось распознать формат изображения")
        fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
        final_url = upload_to_telegraph(img_bytes, fname)

    # --- CLIP CHECK (КЛЮЧЕВОЕ МЕСТО) ---
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        raise HTTPException(400, clip_result["reason"])

    # --- SAVE ---
    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="auto",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "ok", "item": item}

@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    ext = detect_image_type(data)
    if not ext:
        raise HTTPException(400, "Не изображение")

    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    final_url = upload_to_telegraph(data, fname)

    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        raise HTTPException(400, clip_result["reason"])

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="upload",
        image_url=final_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "ok", "item": item}

@router.delete("/{item_id}")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    item = db.query(WardrobeItem).filter_by(id=item_id, user_id=user_id).first()
    if not item:
        raise HTTPException(404, "Вещь не найдена")
    db.delete(item)
    db.commit()
    return {"status": "ok"}
