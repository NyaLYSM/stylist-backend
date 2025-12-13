# routers/wardrobe.py
import io
import requests
import filetype
import os # Добавляем для возможных операций с файлами
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session

from database import get_db
from models import WardrobeItem
from utils.clip_helper import clip_check # Предполагаем, что этот импорт корректен

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
}

# ================== UTILS ==================
def detect_image_type(data: bytes) -> Optional[str]:
    kind = filetype.guess(data)
    if kind and kind.mime in ALLOWED_MIMES:
        return kind.extension
    return None

def validate_name(name: str):
    if len(name.strip()) < 2:
        raise HTTPException(400, "Название должно быть длиннее 2 символов")
    for word in BLACKLIST_WORDS:
        if word in name.lower():
            raise HTTPException(400, "Название содержит запрещенные слова")
        
def upload_to_telegraph(data: bytes, filename: str) -> str:
    """Загружает байты изображения в Telegra.ph."""
    
    # MIME-тип для Telegra.ph всегда должен быть одним из разрешенных типов изображения
    # Используем image/jpeg, так как это наиболее универсальный тип,
    # и Telegra.ph корректно его обрабатывает.
    mime_type = 'image/jpeg' 
    
    # Исправлено: Добавляем явное указание MIME-типа в кортеже файлов
    files = {'file': (filename, data, mime_type)} 
    
    try:
        # Эндпоинт для загрузки файлов в Telegraph
        response = requests.post("https://telegra.ph/upload", files=files, timeout=10)
        response.raise_for_status() # Вызывает исключение при ошибке 4xx/5xx
        
        result = response.json()
        # Telegraph возвращает список с одним элементом: [{'src': '/file/...'}]
        if result and isinstance(result, list) and result[0].get('src'):
            # Возвращаем полный URL
            return "https://telegra.ph" + result[0]['src']
        else:
            # Если ответ не JSON или не соответствует ожидаемому формату
            print(f"Telegraph upload failed. Unexpected response: {result}")
            # Пытаемся получить текст ошибки, если Telegraph вернул 400 с текстом
            error_detail = result.get('error', 'Неизвестный формат ошибки') if isinstance(result, dict) else response.text
            raise Exception(f"Некорректный или ошибочный ответ от Telegraph: {error_detail}")

    except requests.exceptions.RequestException as e:
        # Ошибка сети или таймаут
        print(f"Telegraph upload failed (RequestError): {e}")
        # Если это 400, это означает, что наш запрос был неправильным.
        if response.status_code == 400:
             raise HTTPException(status_code=400, detail="Ошибка Bad Request при отправке в Telegraph. Проверьте формат файла.")
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Telegraph. Сервер недоступен или таймаут.")
    except Exception as e:
        # Ошибка JSON-парсинга или логическая ошибка
        print(f"Telegraph upload failed (LogicError): {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Telegraph: {e}")
# ================== ENDPOINTS ==================

# Роут для получения списка вещей
@router.get("/list")
def get_wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    return {"status": "ok", "items": items}

# Роут для добавления вещи по URL (импорт или прямая ссылка)
@router.post("/add")
def add_item_url(
    user_id: int,
    name: str,
    image_url: str,
    item_type: str,
    db: Session = Depends(get_db)
):
    validate_name(name)

    item = WardrobeItem(
        user_id=user_id,
        name=name,
        item_type=item_type,
        image_url=image_url,
        created_at=datetime.utcnow()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "ok", "item": item}

# Роут для загрузки файла
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
    
    # Используем ИСПРАВЛЕННУЮ функцию загрузки
    final_url = upload_to_telegraph(data, fname) 

    # Проверка CLIP (предполагаем, что этот шаг корректен)
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        # Если CLIP-проверка не пройдена, можно удалить файл из Telegraph
        # (но это опционально и сложно реализуемо без авторизации)
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

# *** ИСПРАВЛЕНО (ПРОБЛЕМА 405): Добавление роута DELETE ***
@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    user_id: int, # Ожидаем user_id как query-параметр из Frontend
    db: Session = Depends(get_db)
):
    """Удаляет вещь из гардероба по ID."""
    # 1. Ищем вещь, убеждаясь, что она принадлежит пользователю
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        # Возвращаем 404, если вещь не найдена или не принадлежит пользователю
        raise HTTPException(status_code=404, detail="Вещь не найдена или нет доступа")

    # 2. Удаляем вещь
    db.delete(item)
    db.commit()

    return {"status": "ok", "message": "Вещь успешно удалена"}
