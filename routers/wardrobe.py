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

from ..database import get_db
from ..models.models import WardrobeItem
from ..utils.clip_helper import clip_check, CLIP_URL # Предполагаем, что CLIP_URL обновлен

router = APIRouter(prefix="/wardrobe", tags=["Wardrobe"])

# ==========================================================
# НОВАЯ ФУНКЦИЯ: СОХРАНЕНИЕ В S3
# ==========================================================
def save_to_s3(data: bytes, filename: str) -> str:
    """Перекодирует изображение в JPEG и сохраняет в Яндекс.Облако Object Storage."""
    
    # 1. Загружаем переменные окружения
    S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

    if not all([S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT_URL]):
        # Это сработает, если вы забыли настроить переменные на Render
        raise HTTPException(500, "Ошибка конфигурации S3: не настроены переменные окружения.")

    # 2. Перекодируем в JPEG в памяти (для оптимизации и сжатия)
    try:
        image = Image.open(io.BytesIO(data))
        # Конвертируем в RGB, чтобы избежать проблем с форматами (например, PNG с прозрачностью)
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        output_buffer = io.BytesIO()
        # Сохраняем в буфер как JPEG с небольшим сжатием
        image.save(output_buffer, format="JPEG", quality=90) 
        output_buffer.seek(0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения: {e}")

    # 3. Подключение к S3 (используем ключи и endpoint Яндекса)
    session = boto3.session.Session()
    s3_client = session.client(
        service_name='s3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY
    )

    # 4. Загрузка в бакет
    s3_key = f"wardrobe/{filename}" # Путь внутри бакета
    try:
        s3_client.upload_fileobj(
            output_buffer,
            S3_BUCKET_NAME,
            s3_key,
            # Указываем тип контента, чтобы браузер знал, что это изображение
            ExtraArgs={'ContentType': 'image/jpeg'} 
        )
        
        # 5. Генерируем публичный URL для доступа
        return f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{s3_key}"
        
    except ClientError as e:
        print(f"S3 Error: {e}")
        raise HTTPException(500, f"Ошибка загрузки в Object Storage: {e}")

# ==========================================================
# УДАЛЯЕМ save_locally, т.к. она больше не нужна
# ==========================================================

# ------------------------------------------------------------------------------------
# Роут /upload: ОБНОВЛЕН
# ------------------------------------------------------------------------------------
@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Валидация данных
    if not (1 <= len(name) <= 100):
        raise HTTPException(400, "Название должно быть от 1 до 100 символов.")
    
    # Чтение данных из файла
    try:
        data = file.file.read()
    except Exception:
        raise HTTPException(400, "Не удалось прочитать файл.")

    # Создание уникального имени файла
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.jpeg"

    # 1. СОХРАНЕНИЕ В S3 И ПОЛУЧЕНИЕ ПУБЛИЧНОГО URL
    final_url = save_to_s3(data, fname) 

    # 2. ПРОВЕРКА CLIP (использует новый публичный URL)
    clip_result = clip_check(final_url, name)
    
    if not clip_result.get("ok"):
        # Если CLIP вернул ошибку, отказываем в загрузке
        reason = clip_result.get("reason", "Проверка CLIP не пройдена.")
        raise HTTPException(400, reason)
        
    # 3. Сохранение в базу данных (URL уже S3-адрес)
    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type="upload",
        image_url=final_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    
    return {"status": "success", "message": "Вещь добавлена и проверена.", "item_id": item.id}

# ------------------------------------------------------------------------------------
# Роут /delete: БЫЛ ПРОБЛЕМНЫМ, ПРОВЕРЯЕМ ЛОГИКУ
# ------------------------------------------------------------------------------------
# ВНИМАНИЕ: Для полной очистки, если вы хотите удалять файл из S3,
# потребуется дополнительная логика. Пока удаляем только из БД.
@router.delete("/delete")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    # Находим вещь в базе данных по ID и user_id
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id, 
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или не принадлежит этому пользователю.")

    # Удаление из базы данных
    db.delete(item)
    db.commit()

    # * * * # ПРИМЕЧАНИЕ: Здесь должна быть логика удаления файла из S3.
    # Сейчас она пропущена для упрощения. Файл остается в S3.
    # * * * return {"status": "success", "message": f"Вещь с ID {item_id} удалена."}

# ------------------------------------------------------------------------------------
# Роут /list: ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ
# ------------------------------------------------------------------------------------
@router.get("/list")
def list_items(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    # Возвращаемые image_url теперь являются постоянными S3-ссылками
    return items
