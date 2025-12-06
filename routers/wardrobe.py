from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import User, WardrobeItem
from datetime import datetime

router = APIRouter()


# ➤ Add item
@router.post("/add")
def add_item(
    user_id: int,
    item_name: str,
    item_type: str,
    photo_url: str,
    colors: str = None,
    description: str = None,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    item = WardrobeItem(
        user_id=user.id,
        item_name=item_name,
        item_type=item_type,
        photo_url=photo_url,
        colors=colors,
        description=description,
        created_at=datetime.utcnow()
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return {"success": True, "item_id": item.id}


# ➤ Get wardrobe items
@router.get("/{user_id}")
def get_wardrobe(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user.id).all()
    return {"items": items}


# ➤ Delete item
@router.delete("/{item_id}")
def delete_item(item_id: int, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.tg_id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    item = db.query(WardrobeItem).filter(
        WardrobeItem.id == item_id,
        WardrobeItem.user_id == user.id
    ).first()

    if not item:
        raise HTTPException(404, "Item not found")

    db.delete(item)
    db.commit()

    return {"success": True}
