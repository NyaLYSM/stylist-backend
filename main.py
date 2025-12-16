import sys
import os

# 1. Определяем директорию, где находится main.py (stylist-backend/)
project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)
# =========================================

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Импорты роутеров и БД
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
# HEALTH CHECK
# ========================================
# Render Health Check
@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}
# ========================================

# 3. Подключение статики (ваши статические файлы, например, изображения)
static_dir_path = os.path.join(project_dir, "static")
image_dir_path = os.path.join(static_dir_path, "images")

os.makedirs(image_dir_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir_path), name="static")

# CORS (оставляем, чтобы WebApp мог подключаться)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# АВТОМАТИЧЕСКАЯ МИГРАЦИЯ (ВРЕМЕННО ЗАКОММЕНТИРОВАНО ДЛЯ FIX TIMEOUT)
# Это позволит приложению немедленно запуститься и ответить на /health
# ==========================================================
# try:
#     from sqlalchemy import inspect
#     with engine.connect() as connection:
#         existing_tables = connection.dialect.get_table_names(connection)
#         if not existing_tables:
#             Base.metadata.create_all(bind=engine)
#             print("✅ БД создана/обновлена!")
#         else:
#             print("✅ БД актуальна")
# except Exception as e:
#     print(f"⚠️  Ошибка при проверке БД: {e}")
#     Base.metadata.create_all(bind=engine) # Оставляем на случай, если таблиц нет, но коннект успешен
# # ==========================================================

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
