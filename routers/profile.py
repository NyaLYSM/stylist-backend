# stylist-backend/routers/profile.py (Изменения)

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, WardrobeItem, Look, Analysis
from ..utils.auth import get_current_user_id # <-- НОВЫЙ ИМПОРТ
from datetime import datetime

router = APIRouter()

# Получить профиль пользователя + последние 5 анализов
@router.get("/") # Изменяем на /
def get_profile(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    # ... (логика)

# Получить все анализы
@router.get("/analyses") # Изменяем на /analyses
def get_analyses(
    limit: int = 20, 
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    # ... (логика)

# Сохранить анализ
@router.post("/analysis/save")
def save_analysis(
    photo_id: str,
    analysis_text: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    # ... (логика)

# Статистика пользователя
@router.get("/stats") # Изменяем на /stats
def get_user_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    # ... (логика)
