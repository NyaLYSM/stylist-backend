from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers import auth, wardrobe, looks, profile, import_router

# Create DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Stylist Backend API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(wardrobe.router, prefix="/api/wardrobe", tags=["wardrobe"])
app.include_router(looks.router, prefix="/api/looks", tags=["looks"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(import_router.router, prefix="/api/import", tags=["import"])


@app.get("/")
def home():
    return {"status": "ok", "message": "Backend работает!"}


@app.get("/health")
def health():
    return {"status": "healthy"}
