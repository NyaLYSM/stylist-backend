# routers/wardrobe.py
import io # *** НОВЫЙ ИМПОРТ ***
import requests
import filetype
import os 
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

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
def get_image_kind(data: bytes) -> Optional[filetype.Type]:
    """Возвращает объект filetype.Type (ext и mime), если файл является разрешенным изображением."""
    kind = filetype.guess(data)
    if kind and kind.mime in ALLOWED_MIMES:
        return kind
    return None

def validate_name(name: str):
    if len(name.strip()) < 2:
        raise HTTPException(400, "Название должно быть длиннее 2 символов")
    for word in BLACKLIST_WORDS:
        if word in name.lower():
            raise HTTPException(400, "Название содержит запрещенные слова")
        
# *** ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ TELEGRAPH: Используем io.BytesIO для надежной отправки данных ***
def upload_to_telegraph(data: bytes, filename: str, mime_type: str) -> str:
    """Загружает байты изображения в Telegra.ph, используя фактический MIME-тип."""
    
    # Оборачиваем байты в буфер, чтобы requests мог правильно обработать multipart/form-data
    file_buffer = io.BytesIO(data)
    files = {'file': (filename, file_buffer, mime_type)} 
    
    try:
        response = requests.post("https://telegra.ph/upload", files=files, timeout=10)
        response.raise_for_status() 
        
        result = response.json()
        
        if result and isinstance(result, list) and result[0].get('src'):
            return "https://telegra.ph" + result[0]['src']
        else:
            print(f"Telegraph upload failed. Unexpected response: {result}")
            error_detail = result.get('error', 'Неизвестный формат ошибки') if isinstance(result, dict) else response.text
            raise Exception(f"Некорректный или ошибочный ответ от Telegraph: {error_detail}")

    except requests.exceptions.RequestException as e:
        print(f"Telegraph upload failed (RequestError): {e}")
        
        detail_msg = "Ошибка Bad Request при отправке в Telegraph. Проверьте формат файла."
        if hasattr(e, 'response') and e.response is not None:
             # Выводим фактический ответ от Telegraph для лучшей диагностики
             detail_msg += f" Ответ Telegraph: {e.response.text}"
             if e.response.status_code == 400:
                raise HTTPException(status_code=400, detail=detail_msg)
        
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Telegraph. Сервер недоступен или таймаут.")
    except Exception as e:
        print(f"Telegraph upload failed (LogicError): {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Telegraph: {e}")

# ================== ENDPOINTS ==================

@router.get("/list")
def get_wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
    return {"status": "ok", "items": items}

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

    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат (проверено по байтам).")

    final_mime_type = image_kind.mime
    ext = image_kind.extension
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    
    # Передаем данные в исправленную функцию
    final_url = upload_to_telegraph(data, fname, final_mime_type) 

    # Проверка CLIP 
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
def delete_item(
    item_id: int,
    user_id: int, 
    db: Session = Depends(get_db)
):
    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Вещь не найдена или нет доступа")

    db.delete(item)
    db.commit()

    return {"status": "ok", "message": "Вещь успешно удалена"}
