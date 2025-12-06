from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User
from datetime import datetime, timedelta
from bot_config_placeholder import TRIAL_PERIOD_DAYS  # we'll replace with env var usage

router = APIRouter()

class UserCreate(BaseModel):
    user_id: int
    username: str = None
    first_name: str = None

@router.post("/register")
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == payload.user_id).first()
    if not user:
        user = User(tg_id=payload.user_id, username=payload.username, first_name=payload.first_name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"success": True, "user": {
        "tg_id": user.tg_id,
        "username": user.username,
        "first_name": user.first_name,
        "subscription_type": user.subscription_type,
        "subscription_until": user.subscription_until,
        "trial_used": user.trial_used
    }}

@router.get("/user/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "tg_id": user.tg_id,
        "username": user.username,
        "first_name": user.first_name,
        "subscription_type": user.subscription_type,
        "subscription_until": user.subscription_until,
        "trial_used": user.trial_used
    }

@router.get("/subscription/{user_id}")
def check_subscription(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    has_premium = False
    if user and user.subscription_type != "free" and user.subscription_until and user.subscription_until > datetime.utcnow():
        has_premium = True
    return {
        "has_premium": has_premium,
        "subscription_type": user.subscription_type if user else "free",
        "subscription_until": user.subscription_until.isoformat() if user and user.subscription_until else None
    }

@router.post("/trial/{user_id}")
def activate_trial(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.trial_used:
        raise HTTPException(status_code=400, detail="Trial already used")
    # TRIAL_PERIOD_DAYS: используем значение из окружения в реальном коде
    days = int(TRIAL_PERIOD_DAYS) if 'TRIAL_PERIOD_DAYS' in globals() else 1
    user.subscription_type = "trial"
    user.subscription_until = datetime.utcnow() + timedelta(days=days)
    user.trial_used = 1
    db.add(user)
    db.commit()
    return {"success": True, "message": "Trial activated"}

@router.post("/subscription/{user_id}")
def activate_subscription(user_id: int, sub_type: str, days: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        user = User(tg_id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    user.subscription_type = sub_type
    user.subscription_until = datetime.utcnow() + timedelta(days=days)
    db.add(user)
    db.commit()
    return {"success": True, "message": "Subscription activated"}
