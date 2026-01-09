# main.py
import sys
import os
import logging

# Настраиваем логирование, чтобы видеть ВСЁ в консоли Render
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

project_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import auth, wardrobe, api_auth, tg_auth
from database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Stylist Backend")

# === CORS НАСТРОЙКА ===
# Указываем конкретный домен фронтенда для работы с credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nyalysm.github.io",  # Ваш фронтенд
        "http://localhost:3000",      # Для локальной разработки
        "http://localhost:5173",
    ],
    allow_credentials=True,  # Разрешаем отправку заголовков авторизации
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],  # Добавлено для полной совместимости
)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 ЗАПУСК СЕРВЕРА...")
    try:
        # Создаем таблицы
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Таблицы базы данных проверены/созданы")
    except Exception as e:
        logger.error(f"❌ ОШИБКА БД ПРИ СТАРТЕ: {e}")

@app.get("/")
def root():
    return {"status": "running", "docs": "/docs"}

@app.get("/health")
def health_check():
    # Простой ответ для проверки связи
    return {"status": "ok"}

# Статика
static_path = os.path.join(project_dir, "static")
os.makedirs(os.path.join(static_path, "images"), exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Роутеры
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(tg_auth.router, prefix="/api/auth", tags=["telegram_auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])


