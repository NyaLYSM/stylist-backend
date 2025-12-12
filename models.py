from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    tg_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    subscription_type = Column(String, default="free") 
    subscription_until = Column(DateTime, nullable=True)
    trial_used = Column(Integer, default=0)

    # Связь с гардеробом
    wardrobe = relationship("WardrobeItem", back_populates="owner", cascade="all, delete-orphan")


class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    # ИСПРАВЛЕНО: user_id ссылается на tg_id, а не на id
    user_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    item_type = Column(String, nullable=True)
    image_url = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связь с владельцем
    owner = relationship("User", back_populates="wardrobe")


class Look(Base):
    __tablename__ = "looks"

    id = Column(Integer, primary_key=True, index=True)
    # ИСПРАВЛЕНО: должно быть tg_id пользователя, а не внутренний id
    user_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False, index=True)
    look_name = Column(String, nullable=True)
    items_ids = Column(Text, nullable=True)  # CSV или JSON строка с ID вещей
    occasion = Column(String, nullable=True)  # Повод (работа, вечеринка и т.д.)
    image_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False, index=True)
    bio = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Если нужна таблица анализов (используется в profile.py)
class Analysis(Base):
    __tablename__ = "analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=False, index=True)
    photo_id = Column(String, nullable=True)
    analysis_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
