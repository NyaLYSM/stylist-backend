# stylist-backend/routers/wardrobe.py

import io
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, UploadFile, HTTPException, File, Form
from sqlalchemy.orm import Session
from PIL import Image

# Импорты для работы с S3
import boto3
from botocore.exceptions import ClientError

# Импорты вашего проекта
from ..database import get_db
from ..models import WardrobeItem
from ..utils.clip_helper import clip_check
from ..utils.auth import get_current_user_id # Защита роутов

router = APIRouter(tags=["Wardrobe"]) # Префикс /api/wardrobe уже задан в main.py

# ==========================================================
# 🛠️ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ S3
# ==========================================================

def get_s3_client():
    """Возвращает настроенный клиент Boto3 S3."""
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

    if not all([S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL]):
        raise HTTPException(500, "Ошибка конфигурации S3: не настроены переменные окружения.")
        
    session = boto3.session.Session()
    return session.client(
        service_name='s3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY
    )

def save_to_s3(data: bytes, filename: str) -> str:
    """Перекодирует изображение в JPEG и сохраняет в Яндекс.Облако Object Storage."""
    
    S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
    if not S3_BUCKET_NAME:
         raise HTTPException(500, "Ошибка конфигурации S3: не настроено имя бакета.")

    s3_client = get_s3_client()
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

    # 1. Обработка изображения (конвертация в JPEG)
    try:
        image = Image.open(io.BytesIO(data))
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        output_buffer = io.BytesIO()
        image.save(output_buffer, format="JPEG", quality=90) 
        output_buffer.seek(0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения: {e}")

    # 2. Загрузка в бакет
    s3_key = f"wardrobe/{filename}"
    try:
        s3_client.upload_fileobj(
            output_buffer,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={'ContentType': 'image/jpeg'} 
        )
        # Возвращаем публичный URL
        return f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{s3_key}"
        
    except ClientError as e:
        print(f"S3 Error: {e}")
        raise HTTPException(500, f"Ошибка загрузки в Object Storage: {e}")

def delete_from_s3(image_url: str):
    """Удаляет файл из Object Storage по его URL."""
    S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
    
    if not S3_BUCKET_NAME or not S3_ENDPOINT_URL:
        return

    # Извлекаем ключ файла (всё после имени бакета)
    base_url = f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/"
    if not image_url.startswith(base_url):
        return

    s3_key = image_url.replace(base_url, "")
    
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
    except Exception as e:
        print(f"Ошибка при удалении из S3: {e}")

# ==========================================================
# 🚦 РОУТЫ API
# ==========================================================

@router.post("/upload")
def upload_item_file(
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # Безопасное получение ID
):
    # 1. Валидация имени
    if not (1 <= len(name) <= 100):
        raise HTTPException(400, "Название должно быть от 1 до 100 символов.")
    
    # 2. Чтение файла
    try:
        data = file.file.read()
    except Exception:
        raise HTTPException(400, "Не удалось прочитать файл.")

    # 3. Сохранение в S3
    # Генерируем уникальное имя файла: user_id + timestamp
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.jpeg"
    final_url = save_to_s3(data, fname)

    # 4. Проверка через CLIP (AI)
    clip_result = clip_check(final_url, name)
    
    if not clip_result.get("ok"):
        # Если проверка не пройдена, удаляем файл из S3, чтобы не мусорить
        delete_from_s3(final_url)
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
    
    return {"status": "success", "message": "Вещь добавлена.", "item_id": item.id, "image_url": final_url}


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
        raise HTTPException(status_code=404, detail="Вещь не найдена.")

    # 1. Удаляем файл из облака
    delete_from_s3(item.image_url)

    # 2. Удаляем запись из БД
    db.delete(item)
    db.commit()

    return {"status": "success", "message": f"Вещь удалена."}


@router.get("/list")
def list_items(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # Безопасное получение ID
):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    return items
