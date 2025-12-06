from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy.orm import declarative_base

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
