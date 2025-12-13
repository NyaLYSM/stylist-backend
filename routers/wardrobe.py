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
# *** НОВЫЙ ИМПОРТ ***
from PIL import Image 
# *** КОНЕЦ НОВОГО ИМПОРТА ***

from database import get_db
from models import WardrobeItem
from utils.clip_helper import clip_check 

router = APIRouter()

# ... (Остальные константы и функции get_image_kind, validate_name остаются без изменений) ...


# *** ФИНАЛЬНАЯ ВЕРСИЯ: ПЕРЕКОДИРОВАНИЕ В СТАНДАРТНЫЙ JPEG ***
def upload_to_telegraph(data: bytes, filename: str, mime_type: str) -> str:
    """Перекодирует изображение в стандартный JPEG и загружает в Telegra.ph."""
    
    final_mime_type = 'image/jpeg' # Для Telegraph всегда отправляем как JPEG
    
    # 1. Загружаем байты в Pillow
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обработки изображения (Pillow): {e}")

    # 2. Конвертируем в RGB (если не RGB) и сохраняем в новый байтовый буфер как JPEG
    output_buffer = io.BytesIO()
    if image.mode != 'RGB':
        image = image.convert('RGB')
        
    # Сохраняем в JPEG с высоким качеством (90)
    image.save(output_buffer, format="JPEG", quality=90) 
    
    # Получаем новые байты для отправки
    processed_data = output_buffer.getvalue()

    # 3. Отправляем перекодированные данные в Telegraph
    files = {'file': (filename, processed_data, final_mime_type)} 
    
    try:
        response = requests.post("https://telegra.ph/upload", files=files, timeout=15) 
        response.raise_for_status() 
        
        result = response.json()
        
        if result and isinstance(result, list) and result[0].get('src'):
            return "https://telegra.ph" + result[0]['src']
        else:
            error_detail = result.get('error', 'Неизвестный формат ответа') if isinstance(result, dict) else response.text
            raise Exception(f"Некорректный или ошибочный ответ от Telegraph: {error_detail}")

    except requests.exceptions.RequestException as e:
        telegraph_error_detail = "Неизвестная ошибка Telegraph."
        
        if hasattr(e, 'response') and e.response is not None:
             response_text = e.response.text
             try:
                 json_data = e.response.json()
                 if isinstance(json_data, dict):
                     telegraph_error_detail = json_data.get('error', response_text)
                 else:
                     telegraph_error_detail = str(json_data)
             except json.JSONDecodeError:
                 telegraph_error_detail = response_text
                 
             print(f"DEBUG: Full Telegraph response: {telegraph_error_detail}") 
             
             if e.response.status_code == 400:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Ошибка загрузки фото. Ответ Telegraph: {telegraph_error_detail}"
                )
        
        raise HTTPException(status_code=503, detail=f"Ошибка загрузки в Telegraph. Сервер недоступен или таймаут. {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки ответа Telegraph: {e}")

# *** Роут /upload также должен быть изменен, чтобы использовать новый MIME-тип ***
@router.post("/upload")
def upload_item_file(
    user_id: int = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, "Неподдерживаемый тип файла")

    # Читаем данные
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Файл больше 5 МБ")

    validate_name(name)

    # Проверка, что это изображение
    image_kind = get_image_kind(data) 
    
    if not image_kind:
        raise HTTPException(400, "Не изображение или неподдерживаемый формат (проверено по байтам).")

    # Расширение для имени файла берем из filetype
    ext = image_kind.extension
    
    fname = f"{user_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    
    # Теперь мы не передаем image_kind.mime, так как функция upload_to_telegraph сама конвертирует
    # в JPEG и использует 'image/jpeg'
    final_url = upload_to_telegraph(data, fname, "image/jpeg") 

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

# ... (Остальные роуты /list, /add, /delete остаются без изменений) ...
