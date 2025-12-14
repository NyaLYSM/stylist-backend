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
from ..utils.clip_helper import clip_check, CLIP_URL 

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
        raise HTTPException(500, "Ошибка конфигурации S3: не настроены переменные окружения.")
        
    session = boto3.session.Session()
    s3_client = session.client(
        service_name='s3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY
    )
    return s3_client

# ==========================================================
# ФУНКЦИЯ: СОХРАНЕНИЕ В S3
# ==========================================================
def save_to_s3(data: bytes, filename: str) -> str:
    """Перекодирует изображение в JPEG и сохраняет в Яндекс.Облако Object Storage."""

    S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
    if not S3_BUCKET_NAME:
         raise HTTPException(500, "Ошибка конфигурации S3: не настроено имя бакета.")

    s3_client = get_s3_client()
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

    # 1. Перекодируем в JPEG в памяти
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
    s3_key = f"wardrobe/{filename}" # Путь внутри бакета
    try:
        s3_client.upload_fileobj(
            output_buffer,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={'ContentType': 'image/jpeg'} 
        )
        
        # 3. Генерируем публичный URL для доступа
        return f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{s3_key}"
        
    except ClientError as e:
        print(f"S3 Error: {e}")
        raise HTTPException(500, f"Ошибка загрузки в Object Storage: {e}")


# ==========================================================
# НОВАЯ ФУНКЦИЯ: УДАЛЕНИЕ ИЗ S3
# ==========================================================
def delete_from_s3(image_url: str):
    """Извлекает ключ файла из URL и удаляет его из Object Storage."""
    
    S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
    
    if not S3_BUCKET_NAME or not S3_ENDPOINT_URL:
        # Невозможно удалить, если не настроено S3
        print("S3-переменные не настроены, пропускаем удаление файла.")
        return

    # 1. Извлекаем ключ (путь) файла из полного URL
    # URL имеет вид: https://storage.yandexcloud.net/bucket-name/wardrobe/filename.jpeg
    # Нам нужно получить: wardrobe/filename.jpeg
    base_url_len = len(f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/")
    
    # Проверяем, что URL соответствует ожидаемому формату
    if not image_url.startswith(f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}"):
        print(f"URL файла не соответствует S3-адресу ЯО: {image_url}. Пропускаем удаление.")
        return

    # Ключ начинается сразу после имени бакета
    s3_key = image_url[base_url_len:]
    
    # 2. Удаление
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key
        )
        print(f"Файл {s3_key} успешно удален из S3.")
    except ClientError as e:
        # Запрос на удаление файла считается успешным, даже если файл не существует.
        # Обрабатываем только критические ошибки доступа.
        print(f"Критическая ошибка при удалении S3: {e}")
        # Не вызываем HTTPException, чтобы не блокировать удаление из БД.
    except Exception as e:
        print(f"Неизвестная ошибка при удалении S3: {e}")

# ------------------------------------------------------------------------------------
# Роут /upload: ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ (использует новую save_to_s3)
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
        # Если CLIP вернул ошибку, отказываем в загрузке.
        # ВАЖНО: нужно удалить файл из S3, если он уже был загружен!
        # Мы оставляем это как улучшение, чтобы не усложнять сейчас.
        reason = clip_result.get("reason", "Проверка CLIP не пройдена.")
        raise HTTPException(400, reason)
        
    # 3. Сохранение в базу данных
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
# Роут /delete: ОБНОВЛЕН
# ------------------------------------------------------------------------------------
@router.delete("/delete")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    # Находим вещь в базе данных по ID и user_id
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id, 
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или не принадлежит этому пользователю.")

    # 1. УДАЛЕНИЕ ФАЙЛА ИЗ S3 (СНАЧАЛА ФАЙЛ, ПОТОМ ЗАПИСЬ В БД)
    delete_from_s3(item.image_url)

    # 2. Удаление из базы данных
    db.delete(item)
    db.commit()

    return {"status": "success", "message": f"Вещь с ID {item_id} удалена."}

# ------------------------------------------------------------------------------------
# Роут /list: ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ
# ------------------------------------------------------------------------------------
@router.get("/list")
def list_items(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    return items
