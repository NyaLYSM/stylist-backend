from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import User
from datetime import datetime, timedelta
import os

router = APIRouter()

TRIAL_PERIOD_DAYS = int(os.getenv("TRIAL_PERIOD_DAYS", 1))


# Register user
# routers/auth.py

# Register user
@router.post("/register")
def register_user(user_id: int, username: str = None, first_name: str = None, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()

    if not user:
        user = User(
            tg_id=user_id,
            username=username,
            first_name=first_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return {"success": True, "user": {
        "tg_id": user.tg_id,
        "subscription_type": user.subscription_type,
        "trial_used": user.trial_used,
        "subscription_until": user.subscription_until
    }}


# Get user
@router.get("/user/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return user


# Check subscription
@router.get("/subscription/{user_id}")
def check_subscription(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    return {
        "has_premium": user.subscription_until and user.subscription_until > datetime.utcnow(),
        "subscription_type": user.subscription_type,
        "subscription_until": user.subscription_until
    }


# Activate trial
@router.post("/trial/{user_id}")
def activate_trial(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if user.trial_used:
        raise HTTPException(400, "Trial already used")

    user.trial_used = 1
    user.subscription_type = "premium"
    user.subscription_until = datetime.utcnow() + timedelta(days=TRIAL_PERIOD_DAYS)

    db.commit()

    return {"success": True, "message": "Trial activated"}


# Activate subscription
@router.post("/subscription/{user_id}")
def activate_subscription(user_id: int, sub_type: str, days: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    user.subscription_type = sub_type
    user.subscription_until = datetime.utcnow() + timedelta(days=days)

    db.commit()
    return {"success": True}
