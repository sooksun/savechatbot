import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, engine
from . import models  # noqa: F401 — register models
from .dashboard import routes as dashboard_routes
from .scheduler import start as start_scheduler, stop as stop_scheduler
from .webhook import router as webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="GetChatBot", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(dashboard_routes.router)
app.mount("/media", StaticFiles(directory=settings.MEDIA_ROOT), name="media")


@app.get("/health")
def health():
    return {"ok": True}
