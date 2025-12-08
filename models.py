from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)   # Telegram user_id
    username = Column(String, nullable=True)
    premium = Column(Integer, default=0)  # 0 = free, 1 = premium

    wardrobe = relationship("WardrobeItem", back_populates="owner")


class WardrobeItem(Base):
    __tablename__ = "wardrobe"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
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
