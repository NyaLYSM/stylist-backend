import sys
import os

# 1. Определяем директорию, где находится main.py (stylist-backend/)
project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)
# =========================================

# 2. Определяем родительскую директорию (AIBOT/), где находится index.html
repo_root = os.path.dirname(project_dir) 

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

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
# HEALTH CHECK (ДОЛЖЕН БЫТЬ ПЕРЕД ДРУГИМИ ЭНДПОИНТАМИ)
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    """Эндпоинт для проверки работоспособности Render Health Check."""
    return {"status": "ok"}
# ========================================

# 3. Подключение статики (Использует АБСОЛЮТНЫЙ путь project_dir)

# Путь к папке static в текущей директории (stylist-backend/static)
static_dir_path = os.path.join(project_dir, "static")
image_dir_path = os.path.join(static_dir_path, "images")

# создаём папку static/images
os.makedirs(image_dir_path, exist_ok=True)

# Монтируем статику по АБСОЛЮТНОМУ пути
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
try:
    from sqlalchemy import inspect
    with engine.connect() as connection:
        existing_tables = connection.dialect.get_table_names(connection)
        needs_migration = False

        if existing_tables and "users" in existing_tables:
            insp = inspect(connection)
            user_columns = [col['name'] for col in insp.get_columns('users')]
            
            if "hashed_password" not in user_columns:
                print("⚠️ Найдена старая схема БД (нет hashed_password). Требуется миграция.")
                pass 

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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Отдает index.html, подставляя динамический URL бэкенда."""
    
    backend_url = os.getenv("RENDER_EXTERNAL_URL") 
    
    # Полный путь к index.html (Использует repo_root - родительскую папку)
    html_file_path = os.path.join(repo_root, "index.html")
    
    try:
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        # Эта ошибка должна указывать на неправильные настройки Render
        return HTMLResponse("index.html not found. Check Render Root Directory configuration.", status_code=500)

    # Запасной локальный адрес для локальной разработки
    final_url = backend_url or "http://127.0.0.1:8000" 
    
    # Заменяем плейсхолдер на реальный URL
    html_content = html_content.replace(
        'window.BACKEND_URL = "{{ BACKEND_URL }}"', 
        f'window.BACKEND_URL = "{final_url}"'
    )
    
    return HTMLResponse(content=html_content, status_code=200)
