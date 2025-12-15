import sys
import os

project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)
# =========================================

# Определяем корневой путь репозитория (на один уровень выше, чем main.py)
# Это путь к папке AIBOT/, где находятся index.html и static/
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
# HEALTH CHECK (для успешного прохождения Render Health Check)
# ========================================
@app.get("/health", include_in_schema=False)
def health_check():
    """Эндпоинт для проверки работоспособности (Render Health Check)"""
    return {"status": "ok"}
# ========================================


# 2. Подключение статики (С ОТЛАДКОЙ)

# Путь к папке static в корне репозитория (AIBOT)
static_dir_path = os.path.join(repo_root, "static")
image_dir_path = os.path.join(static_dir_path, "images")

# Выводим в лог, какой путь используется для статики
print(f"DEBUG: Используется корневая директория репозитория: {repo_root}")
print(f"DEBUG: Ожидаемый путь к static: {static_dir_path}")

try:
    # создаём папку static/images по АБСОЛЮТНОМУ пути
    os.makedirs(image_dir_path, exist_ok=True)

    # Монтируем статику по АБСОЛЮТНОМУ пути
    app.mount("/static", StaticFiles(directory=static_dir_path), name="static")
    print("DEBUG: Папка static успешно смонтирована.")

except Exception as e:
    # Логгируем, если ошибка происходит при монтировании статики
    print(f"FATAL ERROR: Ошибка при монтировании статики: {e}")


# CORS - разрешаем все источники для WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========================================
# АВТОМАТИЧЕСКАЯ МИГРАЦИЯ (Закомментировано для быстрого запуска)
# ========================================

# try:
#     from sqlalchemy import inspect
#     ... (Весь блок миграции закомментирован) ...
# except Exception as e:
#     ... (Весь блок миграции закомментирован) ...

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
    
    backend_url = os.getenv("RENDER_EXTERNAL_URL") 
    
    # Полный путь к index.html (используем repo_root)
    html_file_path = os.path.join(repo_root, "index.html")
    
    # Выводим в лог, какой путь используется для index.html
    print(f"DEBUG: Ожидаемый путь к index.html: {html_file_path}")
    
    try:
        # Читаем шаблон, используя скорректированный путь
        with open(html_file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            print("DEBUG: index.html успешно прочитан.")
    except FileNotFoundError as e:
        # Если файл не найден, выводим подробную ошибку в лог, прежде чем вернуть 500
        print(f"FATAL ERROR: File not found at path: {html_file_path}")
        # Возвращаем 500 с сообщением для отладки
        return HTMLResponse("index.html not found. Check server logs for path details.", status_code=500)
    except Exception as e:
        # Ловим любые другие ошибки чтения
        print(f"FATAL ERROR: Непредвиденная ошибка при чтении index.html: {e}")
        return HTMLResponse(f"Server Error reading HTML: {e}", status_code=500)

    # Запасной локальный адрес для локальной разработки
    final_url = backend_url or "http://127.0.0.1:8000" 
    
    # Заменяем плейсхолдер на реальный URL
    html_content = html_content.replace(
        'window.BACKEND_URL = "{{ BACKEND_URL }}"', 
        f'window.BACKEND_URL = "{final_url}"'
    )
    
    return HTMLResponse(content=html_content, status_code=200)
