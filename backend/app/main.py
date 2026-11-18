import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    analytics, approvals, assistant, auth, campaigns, crm, dashboard, emails, followups, inbox,
    integrations, leads, research, scoring, settings as settings_api, unsubscribe, videos,
)
from app.core.config import production_problems, settings
from app.core.logging import setup_logging
from app.db.seed import seed_demo
from app.db.session import Base, SessionLocal, engine
import app.models  # noqa: F401  (register tables)

setup_logging("DEBUG" if settings.app_env == "development" else "INFO")
log = logging.getLogger(__name__)

_problems = production_problems(settings)
if _problems:
    raise RuntimeError("Refusing to start with APP_ENV=production:\n - " + "\n - ".join(_problems))


def _tick() -> None:
    """Scheduler job: send whatever campaign emails are due."""
    from app.services.campaigns import process_due

    with SessionLocal() as db:
        try:
            stats = process_due(db)
            if stats["sent"] or stats["bounced"]:
                log.info("Scheduler tick: %s", stats)
        except Exception:  # noqa: BLE001 - one bad tick must not stop the scheduler
            log.exception("Scheduler tick failed")
            db.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:  # production with Postgres should use `alembic upgrade head` instead
        Base.metadata.create_all(bind=engine)
    if settings.seed_demo_data:
        with SessionLocal() as db:
            seed_demo(db)
    scheduler = None
    if settings.enable_scheduler:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(_tick, "interval", seconds=60, max_instances=1, coalesce=True, id="send-tick")
        scheduler.start()
        log.info("Scheduler started (checks for due emails every 60 s)")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="AI Outreach Pro API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path not in ("/docs", "/redoc", "/openapi.json"):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if settings.app_env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for module in (
    auth, dashboard, leads, research, scoring, integrations, campaigns, approvals, emails, videos,
    followups, inbox, crm, analytics, settings_api, assistant,
):
    app.include_router(module.router, prefix="/api/v1")
app.include_router(unsubscribe.router)  # public, no /api prefix: links live inside emails


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


# --- Serve the built React app from the same server (single deployable web app) ---
_dist = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
