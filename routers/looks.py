from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import User, Look
from datetime import datetime

router = APIRouter()


# ➤ Save look
@router.post("/save")
def save_look(
    user_id: int,
    look_name: str,
    items_ids: str,
    occasion: str = None,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    new_look = Look(
        user_id=user.id,
        look_name=look_name,
        items_ids=items_ids,   # CSV or JSON string
        occasion=occasion,
        created_at=datetime.utcnow()
    )

    db.add(new_look)
    db.commit()
    db.refresh(new_look)

    return {"success": True, "look_id": new_look.id}


# ➤ Get all looks
@router.get("/{user_id}")
def get_looks(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    looks = db.query(Look).filter(Look.user_id == user.id).order_by(Look.id.desc()).all()
    return {"looks": looks}


# ➤ Delete look
@router.delete("/{look_id}")
def delete_look(look_id: int, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    look = db.query(Look).filter(
        Look.id == look_id,
        Look.user_id == user.id
    ).first()

    if not look:
        raise HTTPException(404, "Look not found")

    db.delete(look)
    db.commit()

    return {"success": True}
