from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    # 1. Мы переименовали id -> tg_id (чтобы auth.py мог его найти)
    tg_id = Column(BigInteger, primary_key=True, index=True)
    
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    
    # 2. Добавлены поля, которые требуются в auth.py
    registered_at = Column(DateTime, default=datetime.utcnow)
    subscription_type = Column(String, default="free") 
    subscription_until = Column(DateTime, nullable=True)
    trial_used = Column(Integer, default=0)

    wardrobe = relationship("WardrobeItem", back_populates="owner")


class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    # Ссылка теперь идет на tg_id
    user_id = Column(BigInteger, ForeignKey("users.tg_id"))
    name = Column(String)
    item_type = Column(String)
    image_url = Column(Text)

    owner = relationship("User", back_populates="wardrobe")


class Look(Base):
    __tablename__ = "looks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger) # Просто храним ID, без жесткой связи
    image_url = Column(Text)
    description = Column(Text, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger)
    bio = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
