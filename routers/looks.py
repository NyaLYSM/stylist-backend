# stylist-backend/routers/looks.py (Изменения)

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Look
from ..utils.auth import get_current_user_id # <-- НОВЫЙ ИМПОРТ
from datetime import datetime

router = APIRouter()

# Сохранить лук
@router.post("/save")
def save_look(
    look_name: str,
    items_ids: str,
    occasion: str = None,
    image_url: str = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    # Убираем лишний поиск user, т.к. user_id теперь tg_id
    # Но для 404 проверки оставим
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    new_look = Look(
        user_id=user.tg_id, # используем безопасный user_id
        look_name=look_name,
        # ...
    )
    # ...

# Получить все луки пользователя
@router.get("/") # Изменяем на /
def get_looks(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    looks = db.query(Look).filter(Look.user_id == user.tg_id).order_by(Look.id.desc()).all()
    return {"looks": looks}

# Удалить лук
@router.delete("/{look_id}")
def delete_look(
    look_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
        
    look = db.query(Look).filter(
        Look.id == look_id,
        Look.user_id == user.tg_id
    ).first()
    # ...
