from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine
from models import User, WardrobeItem, Look, Analysis
from routers import auth, wardrobe, looks, profile
from sqlalchemy import text

# ТОЛЬКО ДЛЯ ИСПРАВЛЕНИЯ - УДАЛИ ПОСЛЕ!
print("🔄 Recreating tables with CASCADE...")
try:
    # Используем raw SQL для CASCADE
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS analyses CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS looks CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS wardrobe CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS payments CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
        conn.commit()
    print("✅ Old tables dropped")
except Exception as e:
    print(f"⚠️ Drop error (ignoring): {e}")

# Создаем новые таблицы
Base.metadata.create_all(bind=engine)
print("✅ New tables created!")

app = FastAPI(title="Stylist Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])

@app.get("/")
def home():
    return {"status": "ok", "message": "Backend работает!"}

@app.get("/health")
def health():
    return {"status": "healthy"}
