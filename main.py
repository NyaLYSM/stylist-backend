import sys
import os

# 1. Определяем директорию, где находится main.py (stylist-backend/)
project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)
# =========================================

# 2. Переменная repo_root больше не нужна, так как index.html не обслуживается.

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import auth, wardrobe, looks, profile, import_router, api_auth, tg_auth 
from database import Base, engine

# ========================================
# FASTAPI APP И ИНИЦИАЛИЗАЦИЯ
# ========================================

app = FastAPI(
    title="Stylist Backend API",
    description="Backend для AI Стилист телеграм бота",
    version="1.0.0"
)

# ========================================
# HEALTH CHECK (обязателен для Render)
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    """Эндпоинт для проверки работоспособности Render Health Check."""
    return {"status": "ok"}
# ========================================

# 3. Подключение статики (Для ваших АПИ-запросов, например, изображений)
# Используем project_dir, так как static/ находится внутри stylist-backend/
static_dir_path = os.path.join(project_dir, "static")
image_dir_path = os.path.join(static_dir_path, "images")

# создаём папку static/images
os.makedirs(image_dir_path, exist_ok=True)

# Монтируем статику по АБСОЛЮТНОМУ пути
# Frontend будет запрашивать: https://stylist-backend-h5jl.onrender.com/static/images/
app.mount("/static", StaticFiles(directory=static_dir_path), name="static")

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
# Оставьте этот блок как есть, если миграция нужна
try:
    from sqlalchemy import inspect
    with engine.connect() as connection:
        existing_tables = connection.dialect.get_table_names(connection)
        needs_migration = False
        # ... (логика проверки БД) ...
        if not existing_tables or needs_migration:
            Base.metadata.create_all(bind=engine)
            print("✅ БД создана/обновлена!")
        else:
            print("✅ БД актуальна")
except Exception as e:
    print(f"⚠️  Ошибка при проверке БД: {e}")
    Base.metadata.create_all(bind=engine)
# ========================================


# ========================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ И ЭНДПОИНТОВ
# ========================================
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(api_auth.router, prefix="/api/auth", tags=["api_auth"]) 
app.include_router(tg_auth.router, prefix="/api/auth", tags=["telegram_auth"]) 
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])

# ========================================
# ГЛАВНЫЙ ЭНДПОИНТ / УДАЛЕН.
# При обращении к корневому URL (/) теперь будет 404, 
# что является НОРМАЛЬНЫМ поведением для API-only сервера.
# ========================================
