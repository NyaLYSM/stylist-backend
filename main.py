from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers import auth, wardrobe, looks, profile, import_router

import models
import os
from fastapi.staticfiles import StaticFiles

# создаём папку static/images если нет
os.makedirs("static/images", exist_ok=True)

# затем после создания app:
app.mount("/static", StaticFiles(directory="static"), name="static")
# ========================================
# АВТОМАТИЧЕСКАЯ ИНИЦИАЛИЗАЦИЯ БД
# ========================================
try:
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    # Проверяем, нужна ли миграция
    needs_migration = False
    if 'wardrobe' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('wardrobe')]
        if 'name' not in columns:
            print("⚠️  Обнаружена старая структура БД. Пересоздание...")
            needs_migration = True
    
    if needs_migration:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("✅ БД успешно обновлена!")
    elif not existing_tables:
        Base.metadata.create_all(bind=engine)
        print("✅ БД создана!")
    else:
        print("✅ БД актуальна")
        
except Exception as e:
    print(f"⚠️  Ошибка при проверке БД: {e}")
    # Пытаемся создать таблицы на всякий случай
    Base.metadata.create_all(bind=engine)

# ========================================
# FASTAPI APP
# ========================================
app = FastAPI(
    title="Stylist Backend API",
    description="Backend для AI Стилист телеграм бота",
    version="1.0.0"
)

# CORS - разрешаем все источники для WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])


@app.get("/")
def home():
    """Главная страница API"""
    return {
        "status": "ok",
        "message": "Stylist Backend работает! 🎨",
        "version": "1.0.0",
        "endpoints": {
            "docs": "/docs",
            "health": "/health"
        }
    }


@app.get("/health")
def health():
    """Проверка здоровья сервиса"""
    return {
        "status": "healthy",
        "database": "connected"
    }
