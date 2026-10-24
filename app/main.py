import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.api import health, complaints, public, notifications, verifications, reviewer, disputes, assessments, authority, auth, admin
from app.services.user_service import UserService

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # In development or testing, initialize SQLite tables and default seed accounts automatically.
    # In production, table creation and default seed resets are prevented; schema management
    # must be executed explicitly via Alembic migrations.
    if settings.is_development_or_test():
        Base.metadata.create_all(bind=engine)
        try:
            with SessionLocal() as db:
                UserService(db).sync_default_seed_accounts()
        except Exception:
            pass
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API for InfraNex AI civic infrastructure reporting and repair-verification platform.",
    lifespan=lifespan
)

# CORS Middleware for mobile emulators and web preview clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register API Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(public.router)
app.include_router(notifications.router)
app.include_router(verifications.router)
app.include_router(reviewer.router)
app.include_router(disputes.router)
app.include_router(assessments.router)
app.include_router(authority.router)
app.include_router(admin.router)


@app.get("/portal", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def serve_web_portal():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "InfraNex AI Web Portal"}


@app.get("/", tags=["Root"])
def read_root(request: Request):
    accept = request.headers.get("accept", "")
    # Serve rich web portal when navigated directly in a browser
    if "text/html" in accept and "application/xhtml+xml" in accept:
        index_file = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)

    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "health_url": "/health",
        "web_portal": "/portal"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
