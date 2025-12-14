# stylist-backend/routers/profile.py (Финальное исправление)

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
# ИСПРАВЛЕНИЕ: Замена относительных импортов на абсолютные
from models import User, WardrobeItem, Look, Analysis
from utils.auth import get_current_user_id 
from datetime import datetime

router = APIRouter(prefix="/profile", tags=["Profile"]) # Добавлен префикс для ясности

# Получить профиль пользователя + последние 5 анализов
@router.get("/") 
def get_profile(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
        
    # Получаем последние 5 анализов
    analyses = db.query(Analysis).filter(Analysis.user_id == user.tg_id).order_by(Analysis.created_at.desc()).limit(5).all()
    
    # Получаем общее количество вещей и луков
    wardrobe_count = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.tg_id).count()
    looks_count = db.query(Look).filter(Look.user_id == user.tg_id).count()
    
    return {
        "profile": {
            "tg_id": user.tg_id,
            "username": user.username,
            "joined_at": user.joined_at,
        },
        "stats": {
            "wardrobe_items": wardrobe_count,
            "looks": looks_count,
            "analyses": len(analyses) # Общее число анализов можно добавить, если нужно
        },
        "latest_analyses": analyses
    }

# Получить все анализы
@router.get("/analyses") 
def get_analyses(
    limit: int = 20, 
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    analyses = db.query(Analysis).filter(Analysis.user_id == user.tg_id).order_by(Analysis.created_at.desc()).limit(limit).all()
    return {"analyses": analyses}

# Сохранить анализ
@router.post("/analysis/save")
def save_analysis(
    photo_id: str,
    analysis_text: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    new_analysis = Analysis(
        user_id=user.tg_id,
        photo_id=photo_id,
        analysis_text=analysis_text,
        created_at=datetime.utcnow()
    )
    db.add(new_analysis)
    db.commit()
    db.refresh(new_analysis)
    
    return {"status": "success", "message": "Анализ сохранен.", "analysis_id": new_analysis.id}

# Статистика пользователя
@router.get("/stats") 
def get_user_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
        
    wardrobe_count = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.tg_id).count()
    looks_count = db.query(Look).filter(Look.user_id == user.tg_id).count()
    analyses_count = db.query(Analysis).filter(Analysis.user_id == user.tg_id).count()
    
    return {
        "wardrobe_items": wardrobe_count,
        "looks": looks_count,
        "analyses": analyses_count
    }
