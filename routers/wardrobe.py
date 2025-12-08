# routers/wardrobe.py
from fastapi import APIRouter, HTTPException
from database import db
from typing import List

router = APIRouter(prefix="/api/wardrobe", tags=["wardrobe"])

@router.get("/{user_id}")
async def get_wardrobe(user_id: int):
    items = await db.get_wardrobe(user_id)
    return {"items": items}

class AddByLinkRequest(BaseModel):
    user_id: int
    url: str

@router.post("/add_by_link")
async def add_by_link(req: AddByLinkRequest):
    # можно просто обёртку над import/add, либо реализовать напрямую
    raise HTTPException(status_code=501, detail="Use /api/import/add instead")
