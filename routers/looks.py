from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User, Look

router = APIRouter()

class LookCreate(BaseModel):
    user_id: int
    look_name: str
    items_ids: str
    occasion: str = None

@router.post("/save")
def save_look(payload: LookCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == payload.user_id).first()
    if not user:
        user = User(tg_id=payload.user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    look = Look(user_id=user.id, look_name=payload.look_name, items_ids=payload.items_ids, occasion=payload.occasion)
    db.add(look)
    db.commit()
    db.refresh(look)
    return {"success": True, "look_id": look.id}

@router.get("/{user_id}")
def get_looks(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        return {"looks": []}
    looks = db.query(Look).filter(Look.user_id == user.id).order_by(Look.created_at.desc()).all()
    return {"looks": [{
        "id": l.id,
        "look_name": l.look_name,
        "items_ids": l.items_ids,
        "occasion": l.occasion
    } for l in looks]}

@router.delete("/{look_id}")
def delete_look(look_id: int, user_id: int, db: Session = Depends(get_db)):
    look = db.query(Look).filter(Look.id == look_id, Look.user_id == user_id).first()
    if not look:
        raise HTTPException(status_code=404, detail="Look not found")
    db.delete(look)
    db.commit()
    return {"success": True}
