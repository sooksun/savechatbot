import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from .config import get_settings
from .database import Base, SessionLocal, engine
from . import models  # noqa: F401 — register models
from .dashboard import routes as dashboard_routes
from .dashboard.auth import hash_password
from .logging_setup import configure_logging
from .models import DashboardUser
from .scheduler import start as start_scheduler, stop as stop_scheduler
from .security import CSRFGuardMiddleware
from .services.embeddings import ensure_collection as ensure_qdrant
from .services.link_metadata import shutdown as shutdown_link_client
from .services.minio_client import ensure_bucket
from .webhook import router as webhook_router

settings = get_settings()
configure_logging(settings.is_production)
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
    # In production we expect migrations to manage schema. Only auto-create
    # tables in development to keep local bootstrap painless.
    if not settings.is_production:
        Base.metadata.create_all(engine)
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    ensure_bucket()
    ensure_qdrant()
    _seed_admin()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        await shutdown_link_client()


limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT_DEFAULT])


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": "Too many requests"}, status_code=429)


app = FastAPI(title="GetChatBot", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CSRFGuardMiddleware)
app.include_router(webhook_router)
app.include_router(dashboard_routes.router)
app.mount("/media", StaticFiles(directory=settings.MEDIA_ROOT), name="media")


@app.get("/health")
def health():
    return {"ok": True}
