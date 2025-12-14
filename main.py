# stylist-backend/main.py

import os
import sys 

# ИСПРАВЛЕНИЕ ДЛЯ ДЕПЛОЯ: 
# Добавляем каталог проекта в путь поиска, чтобы Python нашел 'routers' и 'database'
sys.path.append(os.path.dirname(os.path.abspath(__file__))) 

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ИСПРАВЛЕНО: Используем АБСОЛЮТНЫЕ импорты (без точек, теперь это работает благодаря sys.path)
from routers import auth, wardrobe, looks, profile, import_router, api_auth 
from database import Base, engine 

# ========================================
# FASTAPI APP И ИНИЦИАЛИЗАЦИЯ
# ========================================

# 1. Инициализируем приложение ОДИН РАЗ
app = FastAPI(
    title="Stylist Backend API",
    description="Backend для AI Стилист телеграм бота",
    version="1.0.0"
)

# 2. Подключение статики
# создаём папку static/images если нет
os.makedirs("static/images", exist_ok=True)
# ВАЖНО: Папка "static" должна существовать в корне проекта!
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS - разрешаем все источники для WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========================================
# АВТОМАТИЧЕСКАЯ МИГРАЦИЯ 
# ========================================

try:
    # Проверка, существуют ли таблицы
    existing_tables = engine.dialect.get_table_names(bind=engine)
    needs_migration = False

    if existing_tables and "users" in existing_tables:
        from sqlalchemy import inspect
        insp = inspect(engine)
        user_columns = [col['name'] for col in insp.get_columns('users')]
        # Проверяем наличие нового поля hashed_password
        if "hashed_password" not in user_columns:
            print("⚠️ Найдена старая схема БД (нет hashed_password). Требуется миграция.")
            # В реальном проекте здесь нужен Alembic. Для быстрого запуска:
            # pass # Пропускаем, чтобы не удалять данные
            pass

    if not existing_tables or needs_migration:
        # Создаем таблицы, если их нет или нужна миграция
        Base.metadata.create_all(bind=engine)
        print("✅ БД создана/обновлена!")
    else:
        print("✅ БД актуальна")
        
except Exception as e:
    print(f"⚠️  Ошибка при проверке БД: {e}")
    # Пытаемся создать таблицы на всякий случай
    Base.metadata.create_all(bind=engine)


# ========================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ И ЭНДПОИНТОВ
# ========================================

# Подключаем роутеры
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(api_auth.router, prefix="/api/auth", tags=["api_auth"]) 
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])


@app.get("/")
def home():
    """Главная страница API"""
    return {
        "status": "ok",
        "message": "Stylist Backend работает! 🎨"
    }
