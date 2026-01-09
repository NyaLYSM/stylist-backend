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

# === ВАЖНЫЙ ФИКС CORS ===
# Для Telegram WebApp лучше разрешить всё, но allow_credentials=True 
# требует указания конкретных доменов. 
# Используем компромисс: "*" и allow_credentials=False (так как мы используем Bearer токены, а не куки)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=False, # Важно: False при allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
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

