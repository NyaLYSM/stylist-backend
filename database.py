import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set in Render environment variables!")

# 🔥 ЕСЛИ URL НАЧИНАЕТСЯ С postgres://, ЗАМЕНЯЕМ НА postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 🔥 ДОБАВЛЕНЫ ПАРАМЕТРЫ SSL И POOL ДЛЯ RENDER POSTGRESQL
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "sslmode": "require",  # Обязательно для Render PostgreSQL
    },
    pool_pre_ping=True,      # Проверка соединения перед использованием
    pool_recycle=3600,       # Пересоздание соединений каждый час
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# ---- Dependency for FastAPI ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
