from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)

    subscription_type = Column(String, default="free")
    subscription_until = Column(DateTime, nullable=True)
    trial_used = Column(Integer, default=0)

    wardrobe = relationship("WardrobeItem", back_populates="user", cascade="all, delete-orphan")
    looks = relationship("Look", back_populates="user", cascade="all, delete-orphan")
    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")


class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_name = Column(String)
    item_type = Column(String)
    photo_url = Column(Text)
    colors = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wardrobe")


class Look(Base):
    __tablename__ = "looks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    look_name = Column(String)
    items_ids = Column(Text)
    occasion = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="looks")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    photo_id = Column(String)
    analysis_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="analyses")
