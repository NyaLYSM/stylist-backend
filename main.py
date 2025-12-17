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
# HEALTH CHECK (Render)
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}

# ========================================
# STATIC FILES (/static/images)
# ========================================
static_dir_path = os.path.join(project_dir, "static")
image_dir_path = os.path.join(static_dir_path, "images")

os.makedirs(image_dir_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir_path), name="static")

# ========================================
# CORS (ВАЖНО: без "*", т.к. credentials=True)
# ========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nyalysm.github.io",
        "https://web.telegram.org",
        "https://t.me",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================
# АВТОСОЗДАНИЕ ТАБЛИЦ (опционально)
# ========================================
try:
    from sqlalchemy import inspect
    with engine.connect() as connection:
        inspector = inspect(connection)
        if not inspector.get_table_names():
            Base.metadata.create_all(bind=engine)
            print("✅ БД создана")
        else:
            print("✅ БД уже существует")
except Exception as e:
    print(f"⚠️ Ошибка инициализации БД: {e}")

# ========================================
# РОУТЕРЫ
# ========================================
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(api_auth.router, prefix="/api/auth", tags=["api_auth"])
app.include_router(tg_auth.router, prefix="/api/auth", tags=["telegram_auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])
