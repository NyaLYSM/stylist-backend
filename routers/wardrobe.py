# routers/wardrobe.py
import io 
import requests
import filetype
import os 
import json 
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session
from PIL import Image 

from database import get_db
from models import WardrobeItem
from utils.clip_helper import clip_check 

router = APIRouter()

# ================== PTP.MOE CONFIG ==================
# Простой хостинг, не требующий ключей и не использующий Cloudflare
PTP_UPLOAD_URL = "https://ptp.moe/api/upload"

# ================== LIMITS ==================
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MIMES = ("image/jpeg", "image/png") 

# ================== BLACKLIST/WHITELIST (Остаются без изменений) ==================
BLACKLIST_WORDS = {
    "porn", "sex", "xxx", "nsfw", "нелегаль", "запрет"
}
WHITELIST_KEYWORDS = {
    "футболка","лонгслив","рубашка","поло","майка","топ","кроп","блузка",
    "платье","сарафан","комбинация",
    "джинсы","брюки","штаны","чиносы","леггинсы","лосины",
    "шорты","бермуды",
    "юбка","мини","миди","макси",
    "свитер","джемпер","кофта","кардиган","худи","толстовка","свитшот",
}

# ================== UTILS (Остаются без изменений) ==================
def get_image_kind(data: bytes) -> Optional[filetype.Type]:
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

# *** НОВАЯ ФУНКЦИЯ: ЗАГРУЗКА НА PTP.MOE ***
def upload_to_ptp(data: bytes, filename: str) -> str:
    """Перекодирует изображение в стандартный JPEG и загружает на ptp.moe."""
    
    # 1. Загружаем байты в Pillow для принудительного перекодирования в JPEG
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения (Pillow): {e}")

    # 2. Конвертируем в RGB и сохраняем в новый байтовый буфер как JPEG
    output_buffer = io.BytesIO()
    if image.mode != 'RGB':
        image = image.convert('RGB')
        
    image.save(output_buffer, format="JPEG", quality=90) 
    processed_data = output_buffer.getvalue() # Получаем сырые байты

    # 3. Отправляем данные на PTP.MOE
    
    # PTP.MOE принимает файл в поле 'file'
    files = {
        'file': (filename, processed_data, 'image/jpeg')
    }

    try:
        response = requests.post(PTP_UPLOAD_URL, files=files, timeout=20) 
        response.raise_for_status() 
        
        # PTP.MOE возвращает список, содержащий один объект с прямой ссылкой
        result = response.json()
        
        if isinstance(result, list) and len(result) > 0 and 'link' in result[0]:
            # Ссылка хранится в поле 'link'
            return result[0]['link']
        else:
            # PTP.MOE вернул неожиданный ответ
            error_detail = response.text
            raise Exception(f"Неожиданный ответ PTP.MOE: {error_detail}")

    except requests.exceptions.RequestException as e:
        ptp_error_detail = "Неизвестная ошибка PTP.MOE."
        
        if hasattr(e, 'response') and e.response is not None:
             response_text = e.response.text
             try:
                 # Пытаемся получить JSON-ответ об ошибке
                 json_data = e.response.json()
                 ptp_error_detail = json_data.get('error', response_text)
             except json.JSONDecodeError:
                 ptp_error_detail = response_text
                 
             print(f"DEBUG: Full PTP.MOE response: {ptp_error_detail}") 
             
             raise HTTPException(
                status_code=400, 
                detail=f"Ошибка загрузки фото. Ответ PTP.MOE: {ptp_error_detail}"
            )
        
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в PTP.MOE. Сервер недоступен или таймаут. {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа PTP.MOE: {e}")


# ================== ENDPOINTS ==================

# ... (Роуты /list, /add остаются без изменений) ...

@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Логика проверки файла и имени остается без изменений
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла (требуется JPEG/PNG).")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат.")

    ext = image_kind.extension
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    
    # *** ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ PTP.MOE ***
    final_url = upload_to_ptp(data, fname) 

    # Проверка CLIP 
    clip_result = clip_check(final_url, name)
    if not clip_result["ok"]:
        raise HTTPException(400, clip_result["reason"])

    # Сохранение в базу данных
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

# ... (Роут /delete остается без изменений) ...
