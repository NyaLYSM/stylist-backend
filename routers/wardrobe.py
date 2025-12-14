import os
from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from sqlalchemy.orm import Session

# Абсолютные импорты
from database import get_db
from models import WardrobeItem
from utils.storage import delete_image, save_image
from utils.validators import validate_name, validate_image_bytes
from utils.auth import get_current_user_id
# Если нужен CLIP, раскомментируйте:
from utils.clip_helper import clip_check

# УБРАЛИ prefix="/wardrobe", так как он уже есть в main.py
router = APIRouter(tags=["Wardrobe"])

# --- 1. Список вещей (исправлено под лог /api/wardrobe/list) ---
@router.get("/list")
def get_all_items(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    items = db.query(WardrobeItem).filter(
        WardrobeItem.user_id == user_id
    ).order_by(WardrobeItem.id.desc()).all()
    return {"items": items}

# --- 2. Загрузка вещи (исправлено под лог /api/wardrobe/upload) ---
@router.post("/upload")
async def add_item(
    name: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    # Валидация
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка названия: {name_error}")

    file_bytes = await image.read()
    valid_image, image_error = validate_image_bytes(file_bytes)
    if not valid_image:
        raise HTTPException(400, f"Ошибка файла: {image_error}")

    # Сохранение
    try:
        final_url = save_image(image.filename, file_bytes)
    except Exception as e:
        raise HTTPException(500, f"Ошибка сохранения: {str(e)}")

    # CLIP проверка (если нужна, можно включить)
    # clip_res = clip_check(final_url, name)
    # if not clip_res.get("ok"):
    #     delete_image(final_url)
    #     raise HTTPException(400, clip_res.get("reason", "CLIP error"))

    # Запись в БД
    item = WardrobeItem(
        user_id=user_id,
        name=name.strip(),
        item_type="upload",
        image_url=final_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "success", "item_id": item.id, "image_url": final_url}

# --- 3. Удаление вещи ---
@router.delete("/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(404, "Вещь не найдена")

    delete_image(item.image_url)
    db.delete(item)
    db.commit()

    return {"status": "success", "message": "Deleted"}
