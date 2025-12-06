import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from models import Base, User, WardrobeItem, Look, Analysis

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set in Render environment variables!")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# -------------------------------
#   MAIN DB CLASS
# -------------------------------

class Database:
    def __init__(self):
        self.Session = SessionLocal

    # ----------------------------
    # USERS
    # ----------------------------

    def add_user(self, user_id: int, username: str = None, first_name: str = None):
        with self.Session() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                user = User(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    registered_at=datetime.utcnow()
                )
                db.add(user)
            else:
                user.username = username
                user.first_name = first_name

            db.commit()

    def get_user(self, user_id: int):
        with self.Session() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
            return user.__dict__ if user else None

    def check_subscription(self, user_id: int) -> bool:
        with self.Session() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False
            if not user.subscription_until:
                return False
            return user.subscription_until > datetime.utcnow()

    def activate_trial(self, user_id: int):
        with self.Session() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError("User not found")

            if user.trial_used:
                raise ValueError("Trial already used")

            user.subscription_type = "trial"
            user.subscription_until = datetime.utcnow() + timedelta(days=1)
            user.trial_used = 1

            db.commit()

    def activate_subscription(self, user_id: int, sub_type: str, days: int):
        with self.Session() as db:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError("User not found")

            user.subscription_type = sub_type
            if user.subscription_until and user.subscription_until > datetime.utcnow():
                user.subscription_until += timedelta(days=days)
            else:
                user.subscription_until = datetime.utcnow() + timedelta(days=days)

            db.commit()

    # ----------------------------
    # ANALYSES
    # ----------------------------

    def save_analysis(self, user_id: int, photo_id: str, text: str):
        with self.Session() as db:
            analysis = Analysis(
                user_id=user_id,
                photo_id=photo_id,
                analysis_text=text,
                created_at=datetime.utcnow()
            )
            db.add(analysis)
            db.commit()

    def get_user_analyses(self, user_id: int, limit: int = 10):
        with self.Session() as db:
            analyses = db.query(Analysis).filter(
                Analysis.user_id == user_id
            ).order_by(Analysis.id.desc()).limit(limit).all()

            return [a.__dict__ for a in analyses]

    # ----------------------------
    # WARDROBE
    # ----------------------------

    def add_wardrobe_item(self, user_id: int, name: str, type_: str, photo: str, colors: str, description: str):
        with self.Session() as db:
            item = WardrobeItem(
                user_id=user_id,
                item_name=name,
                item_type=type_,
                photo_url=photo,
                colors=colors,
                description=description,
                created_at=datetime.utcnow()
            )
            db.add(item)
            db.commit()
            return item.id

    def get_wardrobe(self, user_id: int):
        with self.Session() as db:
            items = db.query(WardrobeItem).filter(WardrobeItem.user_id == user_id).all()
            return [i.__dict__ for i in items]

    def delete_wardrobe_item(self, item_id: int, user_id: int):
        with self.Session() as db:
            item = db.query(WardrobeItem).filter(
                WardrobeItem.id == item_id,
                WardrobeItem.user_id == user_id
            ).first()
            if item:
                db.delete(item)
                db.commit()

    # ----------------------------
    # LOOKS
    # ----------------------------

    def save_look(self, user_id: int, name: str, items: str, occasion: str = None):
        with self.Session() as db:
            look = Look(
                user_id=user_id,
                look_name=name,
                items_ids=items,
                occasion=occasion,
                created_at=datetime.utcnow()
            )
            db.add(look)
            db.commit()
            return look.id

    def get_user_looks(self, user_id: int):
        with self.Session() as db:
            looks = db.query(Look).filter(Look.user_id == user_id).all()
            return [l.__dict__ for l in looks]

    def delete_look(self, look_id: int, user_id: int):
        with self.Session() as db:
            look = db.query(Look).filter(
                Look.id == look_id,
                Look.user_id == user_id
            ).first()
            if look:
                db.delete(look)
                db.commit()


# global instance
db = Database()

