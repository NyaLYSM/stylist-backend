from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User, Analysis, WardrobeItem, Look

router = APIRouter()

class AnalysisCreate(BaseModel):
    user_id: int
    photo_id: str
    analysis_text: str

@router.get("/{user_id}")
def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    has_premium = user.subscription_type != "free" and user.subscription_until and user.subscription_until > __import__("datetime").datetime.utcnow()
    analyses = db.query(Analysis).filter(Analysis.user_id == user.id).order_by(Analysis.created_at.desc()).limit(5).all()
    return {
        "user": {
            "tg_id": user.tg_id,
            "username": user.username,
            "first_name": user.first_name,
            "subscription_type": user.subscription_type,
            "subscription_until": user.subscription_until
        },
        "has_premium": has_premium,
        "recent_analyses": [{"id": a.id, "photo_id": a.photo_id, "analysis_text": a.analysis_text} for a in analyses]
    }

@router.get("/analyses/{user_id}")
def get_analyses(user_id: int, limit: int = 10, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        return {"analyses": []}
    analyses = db.query(Analysis).filter(Analysis.user_id == user.id).order_by(Analysis.created_at.desc()).limit(limit).all()
    return {"analyses": [{"id": a.id, "photo_id": a.photo_id, "analysis_text": a.analysis_text} for a in analyses]}

@router.post("/analysis/save")
def save_analysis(payload: AnalysisCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == payload.user_id).first()
    if not user:
        user = User(tg_id=payload.user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    analysis = Analysis(user_id=user.id, photo_id=payload.photo_id, analysis_text=payload.analysis_text)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return {"success": True, "id": analysis.id}

@router.get("/stats/{user_id}")
def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wardrobe_count = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.id).count()
    looks_count = db.query(Look).filter(Look.user_id == user.id).count()
    analyses_count = db.query(Analysis).filter(Analysis.user_id == user.id).count()
    return {
        "wardrobe_items": wardrobe_count,
        "saved_looks": looks_count,
        "total_analyses": analyses_count,
        "subscription_type": user.subscription_type
    }
