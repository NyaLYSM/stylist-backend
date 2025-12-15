import sys
import os

project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)
# =========================================

# Определяем корневой путь репозитория (на один уровень выше, чем main.py)
# Если Render развертывает AIBOT/, это будет его корневая папка
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
# HEALTH CHECK
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}
# ========================================


# 2. Подключение статики (Использует repo_root - родительскую папку)

# Путь к папке static в корне репозитория (AIBOT)
static_dir_path = os.path.join(repo_root, "static")
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

# ... (Подключение роутеров и миграция)

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Отдает index.html, подставляя динамический URL бэкенда."""
    
    backend_url = os.getenv("RENDER_EXTERNAL_URL") 
    
    # Полный путь к index.html (Использует repo_root - родительскую папку)
    html_file_path = os.path.join(repo_root, "index.html")
    
    try:
        # Читаем шаблон, используя скорректированный путь
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        return HTMLResponse("index.html not found. Render failed to deploy the file.", status_code=500)

    # ... (Остальной код)
