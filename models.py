from sqlalchemy import Column, Integer, String
from database import Base

class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    name = Column(String)
    image_url = Column(String)
    item_type = Column(String)
