from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import WardrobeItem

router = APIRouter()

@router.get("/list")
def wardrobe_list(user_id: int, db: Session = Depends(get_db)):
    items = db.query(WardrobeItem).filter_by(user_id=user_id).all()
    return {"items": items}

@router.post("/add")
def add_item(payload: dict, db: Session = Depends(get_db)):
    item = WardrobeItem(
        user_id=payload["user_id"],
        name=payload["name"],
        image_url=payload["image_url"],
        item_type=payload.get("item_type", "unknown")
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "ok", "item": item}
