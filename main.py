from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from app.database import init_db
from app.services.index import load_index
from app.routers import search, admin, recommendations
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    await init_db()
    load_index()
    yield
    # Shutdown — nothing to clean up


app = FastAPI(title="skill-finder", version="0.1.0", lifespan=lifespan)

app.include_router(search.router)
app.include_router(recommendations.router)
app.include_router(admin.router)

# Serve frontend
frontend_dir = Path(__file__).parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(frontend_dir / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}
