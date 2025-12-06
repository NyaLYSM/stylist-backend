from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from models import User, WardrobeItem

router = APIRouter()

class WardrobeItemCreate(BaseModel):
    user_id: int
    item_name: str
    item_type: str
    photo_url: str
    colors: str = None
    description: str = None

@router.post("/add")
def add_item(payload: WardrobeItemCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == payload.user_id).first()
    if not user:
        user = User(tg_id=payload.user_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    item = WardrobeItem(
        user_id=user.id,
        item_name=payload.item_name,
        item_type=payload.item_type,
        photo_url=payload.photo_url,
        colors=payload.colors,
        description=payload.description
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"success": True, "item_id": item.id}

@router.get("/{user_id}")
def get_wardrobe(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        return {"items": []}
    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.id).order_by(WardrobeItem.created_at.desc()).all()
    return {"items": [{
        "id": i.id,
        "item_name": i.item_name,
        "item_type": i.item_type,
        "photo_url": i.photo_url,
        "colors": i.colors,
        "description": i.description
    } for i in items]}

@router.delete("/{item_id}")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    item = db.query(WardrobeItem).filter(WardrobeItem.id == item_id, WardrobeItem.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"success": True}
