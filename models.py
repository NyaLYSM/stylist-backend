from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime # Обязательно импортируем datetime

class User(Base):
    __tablename__ = "users"

    # ИСПРАВЛЕНИЕ 1: Переименовываем id в tg_id, чтобы соответствовать auth.py
    tg_id = Column(BigInteger, primary_key=True, index=True)   

    # ДОБАВЛЯЕМ НЕДОСТАЮЩИЕ КОЛОНКИ
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True) # ИСПОЛЬЗУЕТСЯ в auth.py
    registered_at = Column(DateTime, default=datetime.utcnow) # Рекомендуется для отслеживания
    subscription_type = Column(String, default="free") # ИСПОЛЬЗУЕТСЯ в auth.py
    subscription_until = Column(DateTime, nullable=True) # ИСПОЛЬЗУЕТСЯ в auth.py
    trial_used = Column(Integer, default=0) # ИСПОЛЬЗУЕТСЯ в auth.py

    wardrobe = relationship("WardrobeItem", back_populates="owner")


class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    # ИСПРАВЛЕНИЕ 2: Обновляем внешний ключ, чтобы он указывал на tg_id
    user_id = Column(BigInteger, ForeignKey("users.tg_id")) 
    name = Column(String)
    item_type = Column(String)
    image_url = Column(Text)

    owner = relationship("User", back_populates="wardrobe")
class Look(Base):
    __tablename__ = "looks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger)
    image_url = Column(Text)
    description = Column(Text, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger)
    bio = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)

