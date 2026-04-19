import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, SessionLocal, engine
from . import models  # noqa: F401 — register models
from .dashboard import routes as dashboard_routes
from .dashboard.auth import hash_password
from .models import DashboardUser
from .scheduler import start as start_scheduler, stop as stop_scheduler
from .webhook import router as webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()
log = logging.getLogger(__name__)


def _seed_admin() -> None:
    """Create default admin from .env if no users exist yet."""
    db = SessionLocal()
    try:
        if db.query(DashboardUser).count() == 0:
            db.add(DashboardUser(
                username=settings.DASHBOARD_USER,
                password_hash=hash_password(settings.DASHBOARD_PASSWORD),
                role="admin",
            ))
            db.commit()
            log.info("Created default admin user: %s", settings.DASHBOARD_USER)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    _seed_admin()
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
