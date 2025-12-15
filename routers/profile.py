# routers/profile.py

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional

from database import get_db
# ИСПРАВЛЕНИЕ 1: Изменяем относительные импорты на абсолютные
from models import User, WardrobeItem, Look, Analysis 
from utils.auth import get_current_user_id 

# ИСПРАВЛЕНИЕ 2: Инициализируем APIRouter
router = APIRouter(tags=["Profile"])

# ------------------------------------------------------------------------------------
# Роут /: Получить профиль пользователя + последние 5 анализов
# ------------------------------------------------------------------------------------
@router.get("/")
def get_profile(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Получаем последние 5 анализов
    latest_analyses = db.query(Analysis).filter(
        Analysis.user_id == user_id
    ).order_by(Analysis.id.desc()).limit(5).all()

    # ИСПРАВЛЕНИЕ: Динамическое создание full_name и безопасный доступ к полям
    # Используем getattr для безопасного доступа к полям, которые могли быть только что добавлены
    first_name = getattr(user, 'first_name', None) or ''
    last_name = getattr(user, 'last_name', None) or ''
    username = getattr(user, 'username', None) or ''
    last_login = getattr(user, 'last_login', None)
    
    # Собираем полное имя
    full_name = f"{first_name} {last_name}".strip()
    # Если имени нет, используем юзернейм или ID
    if not full_name:
        full_name = username if username else f"User {user.tg_id}"

    return {
        "user": {
            "tg_id": user.tg_id,
            "username": username,
            "full_name": full_name, # <-- ИСПРАВЛЕНО
            "last_login": last_login, # <-- Теперь безопасно извлекается
        },
        "latest_analyses": latest_analyses
    }


# ------------------------------------------------------------------------------------
# Роут /analyses: Получить все анализы
# ------------------------------------------------------------------------------------
@router.get("/analyses") 
def get_analyses(
    limit: int = 20, 
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    # Проверяем существование пользователя (хотя get_current_user_id уже должен это делать)
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    analyses = db.query(Analysis).filter(
        Analysis.user_id == user_id
    ).order_by(Analysis.id.desc()).limit(limit).all()
    
    return {"analyses": analyses}


# ------------------------------------------------------------------------------------
# Роут /analysis/save: Сохранить анализ
# ------------------------------------------------------------------------------------
@router.post("/analysis/save")
def save_analysis(
    photo_id: str,
    analysis_text: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id) # <-- ЗАЩИТА
):
    # Проверяем существование пользователя 
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Создаем новую запись анализа
    new_analysis = Analysis(
        user_id=user_id,
        photo_id=photo_id,
        analysis_text=analysis_text,
        created_at=datetime.utcnow()
    )
    
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)
    
    return {"status": "success", "analysis_id": new_analysis.id}
