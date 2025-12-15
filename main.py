import sys
import os

project_root = os.path.abspath(os.path.dirname(__file__))

sys.path.insert(0, project_root)
# =========================================

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from routers import auth, wardrobe, looks, profile, import_router, api_auth, tg_auth 
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
    from sqlalchemy import inspect
    # ИСПРАВЛЕНИЕ: Используем активное подключение для инспекции БД
    with engine.connect() as connection:
        
        # ИСПРАВЛЕНИЕ ОШИБКИ: PGDialect.get_table_names требует объект connection
        existing_tables = connection.dialect.get_table_names(connection)
        needs_migration = False

        if existing_tables and "users" in existing_tables:
            # Используем инспектор для текущего подключения
            insp = inspect(connection)
            user_columns = [col['name'] for col in insp.get_columns('users')]
            
            # Проверяем наличие нового поля hashed_password
            if "hashed_password" not in user_columns:
                print("⚠️ Найдена старая схема БД (нет hashed_password). Требуется миграция.")
                # pass остается, чтобы пропустить миграцию без Alembic
                pass 

        if not existing_tables or needs_migration:
            # Создаем таблицы, если их нет или нужна миграция
            Base.metadata.create_all(bind=engine)
            print("✅ БД создана/обновлена!")
        else:
            print("✅ БД актуальна")
            
except Exception as e:
    print(f"⚠️  Ошибка при проверке БД: {e}")
    # Пытаемся создать таблицы на случай, если сама проверка упала. 
    # SQLAlchemy пропустит уже существующие таблицы.
    Base.metadata.create_all(bind=engine)

# ========================================


# ========================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ И ЭНДПОИНТОВ
# ========================================

# Подключаем роутеры
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(api_auth.router, prefix="/api/auth", tags=["api_auth"]) 
app.include_router(tg_auth.router, prefix="/api/auth", tags=["telegram_auth"]) 
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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Отдает index.html, подставляя динамический URL бэкенда."""
    
    # RENDER_EXTERNAL_URL - переменная, которую Render устанавливает автоматически
    backend_url = os.getenv("RENDER_EXTERNAL_URL") 
    
    try:
        # Читаем шаблон
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        return HTMLResponse("index.html not found", status_code=500)

    # Запасной локальный адрес для локальной разработки
    final_url = backend_url or "http://127.0.0.1:8000" 
    
    # Заменяем плейсхолдер на реальный URL
    html_content = html_content.replace(
        'window.BACKEND_URL = "{{ BACKEND_URL }}"', 
        f'window.BACKEND_URL = "{final_url}"'
    )
    
    return HTMLResponse(content=html_content, status_code=200)
