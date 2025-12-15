import sys
import os

project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)
# =========================================

# Определяем корневой путь репозитория (на один уровень выше, чем main.py)
repo_root = os.path.dirname(project_root) 

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

# ========================================
# HEALTH CHECK 
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    """Эндпоинт для проверки работоспособности (Render Health Check)"""
    return {"status": "ok"}
# ========================================


# 2. Подключение статики (ИСПРАВЛЕНО: использует абсолютный путь repo_root)

# Путь к папке static в корне репозитория (AIBOT)
static_dir_path = os.path.join(repo_root, "static")

# Путь к папке images внутри static
image_dir_path = os.path.join(static_dir_path, "images")

# создаём папку static/images по АБСОЛЮТНОМУ пути, если ее нет
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
# АВТОМАТИЧЕСКАЯ МИГРАЦИЯ (Оставляем закомментированной для быстрого запуска)
# ========================================

# try:
#     from sqlalchemy import inspect
#     # ... (Весь блок миграции закомментирован) ...
# except Exception as e:
#     # ... (Весь блок миграции закомментирован) ...

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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Отдает index.html, подставляя динамический URL бэкенда."""
    
    # RENDER_EXTERNAL_URL - переменная, которую Render устанавливает автоматически
    backend_url = os.getenv("RENDER_EXTERNAL_URL") 
    
    # Полный путь к index.html (используем repo_root)
    html_file_path = os.path.join(repo_root, "index.html")
    
    try:
        # Читаем шаблон, используя скорректированный путь
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        # Если файл не найден, возвращаем 500
        return HTMLResponse("index.html not found", status_code=500)

    # Запасной локальный адрес для локальной разработки
    final_url = backend_url or "http://127.0.0.1:8000" 
    
    # Заменяем плейсхолдер на реальный URL
    html_content = html_content.replace(
        'window.BACKEND_URL = "{{ BACKEND_URL }}"', 
        f'window.BACKEND_URL = "{final_url}"'
    )
    
    return HTMLResponse(content=html_content, status_code=200)
