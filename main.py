from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import Base, engine
from routers import auth, wardrobe, looks, profile
from models import Base
from database import engine
from routers import auth, wardrobe, looks, profile
from routers import importer   # <— добавь это

app.include_router(importer.router)

Base.metadata.create_all(bind=engine)


app = FastAPI(title="Stylist Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Attach routers
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
