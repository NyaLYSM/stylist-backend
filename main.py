import sys
import os

# 1. Определяем директорию, где находится main.py (stylist-backend/)
project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)

from fastapi import FastAPI, Request
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
# HEALTH CHECK (Render) - ДОЛЖЕН БЫТЬ ПЕРВЫМ
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
# CORS - ПРАВИЛЬНАЯ КОНФИГУРАЦИЯ
# ========================================
# ВАЖНО: Указываем конкретные домены вместо "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nyalysm.github.io",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,  # Теперь можно True
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# ========================================
# ДОПОЛНИТЕЛЬНЫЙ MIDDLEWARE ДЛЯ CORS
# ========================================
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    """
    Дополнительная обработка CORS заголовков.
    Это нужно для некоторых браузеров в Telegram WebApp.
    """
    origin = request.headers.get("origin", "")
    
    # Обрабатываем preflight запросы
    if request.method == "OPTIONS":
        from fastapi.responses import Response
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = origin or "https://nyalysm.github.io"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Max-Age"] = "3600"
        return response
    
    # Обычные запросы - вызываем endpoint
    try:
        response = await call_next(request)
    except Exception as e:
        # Даже при ошибке добавляем CORS
        from fastapi.responses import JSONResponse
        response = JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )
    
    # Добавляем CORS заголовки к ЛЮБОМУ ответу (включая ошибки)
    if origin in ["https://nyalysm.github.io", "http://localhost:3000", "http://localhost:8000"]:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    elif origin:  # Если origin есть, но не в whitelist
        response.headers["Access-Control-Allow-Origin"] = "https://nyalysm.github.io"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response

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
# Обработка OPTIONS для всех путей (CORS preflight)
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return {"status": "ok"}

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(api_auth.router, prefix="/api/auth", tags=["api_auth"])
app.include_router(tg_auth.router, prefix="/api/auth", tags=["telegram_auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])
