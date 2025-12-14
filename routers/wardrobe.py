# routers/wardrobe.py

from datetime import datetime
import io
import os
import shutil

from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from sqlalchemy.orm import Session
from PIL import Image

# НОВЫЕ ИМПОРТЫ ДЛЯ S3
import boto3
from botocore.exceptions import ClientError

# ==========================================================
# ИСПРАВЛЕННЫЕ АБСОЛЮТНЫЕ ИМПОРТЫ
# ==========================================================
from database import get_db
from models import WardrobeItem 
from utils.clip_helper import clip_check, CLIP_URL 
from utils.storage import delete_image, save_image
from utils.validators import validate_name, validate_image_bytes
from utils.auth import get_current_user_id # КРИТИЧЕСКИ ВАЖНЫЙ ИМПОРТ

router = APIRouter(prefix="/wardrobe", tags=["Wardrobe"])

# ==========================================================
# ФУНКЦИЯ: ПОДКЛЮЧЕНИЕ КЛИЕНТА S3
# ==========================================================
def get_s3_client():
    """Возвращает настроенный клиент Boto3 S3."""
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

    if not all([S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL]):
        raise HTTPException(status_code=500, detail="Ошибка конфигурации S3: не настроены переменные окружения.")
        
    session = boto3.session.Session()
    s3_client = session.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY
    )
    return s3_client


# ------------------------------------------------------------------------------------
# Роут /all: Получить все вещи пользователя
# ------------------------------------------------------------------------------------
@router.get("/all")
def get_all_items(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # Безопасное получение ID
):
    items = db.query(WardrobeItem).filter(
        WardrobeItem.user_id == user_id
    ).order_by(WardrobeItem.id.desc()).all()
    
    return {"items": items}


# ------------------------------------------------------------------------------------
# Роут /add: Добавить вещь
# ------------------------------------------------------------------------------------
@router.post("/add")
async def add_item(
    name: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # Безопасное получение ID
):
    # 1. Валидация имени
    valid_name, name_error = validate_name(name)
    if not valid_name:
        raise HTTPException(400, f"Ошибка в названии: {name_error}")
    
    # Очистка имени
    name = name.strip()

    # 2. Чтение и валидация файла
    file_bytes = await image.read()
    valid_image, image_error = validate_image_bytes(file_bytes)
    if not valid_image:
        raise HTTPException(400, f"Ошибка в файле: {image_error}")

    # 3. Сохранение файла (S3 или локально)
    try:
        final_url = save_image(image.filename, file_bytes)
    except Exception as e:
        # Обычно это ошибка S3 или прав доступа к файловой системе
        raise HTTPException(500, f"Не удалось сохранить файл: {str(e)}")


    # 4. Проверка через CLIP (может занять время)
    clip_result = clip_check(final_url, name)
    
    if not clip_result.get("ok"):
        # Если проверка не пройдена, удаляем файл
        delete_image(final_url) 
        reason = clip_result.get("reason", "Проверка CLIP не пройдена.")
        raise HTTPException(400, reason)
        
    # 5. Сохранение записи в БД
    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="upload",
        image_url=final_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    
    return {"status": "success", "message": "Вещь добавлена и проверена.", "item_id": item.id, "image_url": final_url}


# ------------------------------------------------------------------------------------
# Роут /delete: Удалить вещь
# ------------------------------------------------------------------------------------
@router.delete("/delete")
def delete_item(
    item_id: int, 
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # Безопасное получение ID
):
    # Ищем вещь, которая принадлежит именно этому пользователю
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id, 
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или не принадлежит этому пользователю.")

    # 1. Удаляем файл из облака/локальной папки
    if not delete_image(item.image_url):
        # Логгируем ошибку, но продолжаем, так как запись в БД важнее
        print(f"⚠️ Ошибка при удалении файла: {item.image_url}")

    # 2. Удаление из базы данных
    db.delete(item)
    db.commit()

    return {"status": "success", "message": f"Вещь с ID {item_id} удалена."}
