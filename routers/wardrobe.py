# routers/wardrobe.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem, User
from pathlib import Path
from PIL import Image, UnidentifiedImageError
import os
import uuid
import re
import io
import cv2
import numpy as np

router = APIRouter()

# where to store images locally (relative to project)
IMAGES_DIR = Path("static/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# max file size bytes (5 MB)
MAX_FILE_BYTES = 5 * 1024 * 1024

# simple name sanitization regex (allow letters, numbers, space, dash, underscore)
NAME_RE = re.compile(r"^[\w\s\-\u0400-\u04FF]{1,120}$", re.UNICODE)

# face detector (Haar cascade) — uses cv2's bundled cascades
_face_cascade = None
try:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    _face_cascade = cv2.CascadeClassifier(cascade_path)
except Exception:
    _face_cascade = None


def detect_faces_bytes(image_bytes: bytes):
    """Return number of detected faces or 0 (requires OpenCV)."""
    if _face_cascade is None:
        return 0
    try:
        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return 0
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return int(len(faces))
    except Exception:
        return 0


def save_image_bytes(image_bytes: bytes, ext: str = ".jpg") -> str:
    """Save bytes to static/images with unique name, return relative path."""
    filename = f"{uuid.uuid4().hex}{ext}"
    path = IMAGES_DIR / filename
    with open(path, "wb") as f:
        f.write(image_bytes)
    return f"/static/images/{filename}"


@router.get("/list")
def wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter_by(user_id=user_id).all()
    return {"items": items}


@router.post("/add")
async def add_item(
    request: Request,
    # optional form fields
    user_id: int = Form(...),
    name: str = Form(...),
    item_type: str = Form("unknown"),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db)
):
    """
    Add wardrobe item.
    Accepts multipart/form-data with fields:
      - user_id (int)
      - name (str)
      - item_type (str, optional)
      - file (image file, optional)
    Or you can continue to call /add from frontend as JSON (existing endpoint kept below).
    """

    # basic name sanitization
    if not NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Неподдерживаемое название — используйте только буквы/цифры/пробел/-,_")

    # verify user exists (optional but helpful)
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # file upload path
    image_url = None
    warning = None

    if file:
        # check content-type
        if not (file.content_type and file.content_type.startswith("image/")):
            raise HTTPException(400, "Файл не является изображением")

        # read in memory (but limit)
        contents = await file.read()
        if len(contents) > MAX_FILE_BYTES:
            raise HTTPException(400, "Файл слишком большой (максимум 5 МБ)")

        # verify image via Pillow
        try:
            img = Image.open(io.BytesIO(contents))
            img.verify()  # will raise if not image
        except UnidentifiedImageError:
            raise HTTPException(400, "Невозможно распознать изображение")
        except Exception:
            raise HTTPException(400, "Ошибка обработки изображения")

        # detect faces (if any) — return as warning to UI
        faces = detect_faces_bytes(contents)
        if faces > 0:
            warning = {"type": "face_detected", "faces": faces}

        # choose extension based on original filename or image format
        ext = Path(file.filename).suffix.lower() if file.filename else ""
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".avif"):
            # try PIL format
            fmt = getattr(img, "format", None)
            ext = f".{fmt.lower()}" if fmt else ".jpg"

        image_url = save_image_bytes(contents, ext=ext)

    else:
        # if no file - maybe frontend sends JSON via request body
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # fallback to image_url in JSON (link import)
        image_url = payload.get("image_url") or payload.get("url")
        if not image_url:
            raise HTTPException(400, "Нет файла и нет image_url")

    # create DB item
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type=item_type,
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    result = {"status": "ok", "item": item}
    if warning:
        result["warning"] = warning

    return result


# keep old JSON style endpoint for compatibility (optional)
@router.post("/add_json")
def add_item_json(payload: dict, db: Session = Depends(get_db)):
    """Legacy: accepts JSON payload with keys user_id, name, image_url, item_type"""
    user_id = payload.get("user_id")
    name = payload.get("name")
    image_url = payload.get("image_url")
    if not all([user_id, name, image_url]):
        raise HTTPException(400, "user_id, name и image_url обязательны")
    if not NAME_RE.match(name):
        raise HTTPException(400, "Неподдерживаемое название")

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type=payload.get("item_type", "unknown"),
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": item}
