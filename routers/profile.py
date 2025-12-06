from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import User, WardrobeItem, Look, Analysis
from datetime import datetime

router = APIRouter()


# ➤ Get user profile + last 5 analyses
@router.get("/{user_id}")
def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    analyses = db.query(Analysis).filter(
        Analysis.user_id == user.id
    ).order_by(Analysis.id.desc()).limit(5).all()

    has_premium = user.subscription_until and user.subscription_until > datetime.utcnow()

    return {
        "user": user,
        "has_premium": bool(has_premium),
        "recent_analyses": analyses
    }


# ➤ Get all analyses
@router.get("/analyses/{user_id}")
def get_analyses(user_id: int, limit: int = 10, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    analyses = db.query(Analysis).filter(
        Analysis.user_id == user.id
    ).order_by(Analysis.id.desc()).limit(limit).all()

    return {"analyses": analyses}


# ➤ Save analysis
@router.post("/analysis/save")
def save_analysis(
    user_id: int,
    photo_id: str,
    analysis_text: str,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    record = Analysis(
        user_id=user.id,
        photo_id=photo_id,
        analysis_text=analysis_text,
        created_at=datetime.utcnow()
    )

    db.add(record)
    db.commit()

    return {"success": True}


# ➤ Stats
@router.get("/stats/{user_id}")
def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    wardrobe = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.id).count()
    looks = db.query(Look).filter(Look.user_id == user.id).count()
    analyses = db.query(Analysis).filter(Analysis.user_id == user.id).count()

    return {
        "wardrobe_items": wardrobe,
        "saved_looks": looks,
        "total_analyses": analyses,
        "subscription_type": user.subscription_type,
        "premium_active": bool(user.subscription_until and user.subscription_until > datetime.utcnow())
    }
