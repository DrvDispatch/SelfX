"""FastAPI app: routers, startup tasks, hourly retention loop, healthz (SPEC §5, §10)."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select, text
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import hash_password
from .cleanup import run_cleanup
from .config import check_secret_key, settings
from .db import SessionLocal, engine, init_db
from .models import User
from .queueing import redis_conn
from .ratelimit import limiter
from .routes import admin as admin_routes
from .routes import agent as agent_routes
from .routes import auth as auth_routes
from .routes import files as files_routes
from .routes import jobs as jobs_routes
from .routes import kb as kb_routes
from .routes import models as models_routes
from .routes import presets as presets_routes
from .routes import tools as tools_routes
from .routes import workflows as workflows_routes
from .services.workflows import reconcile_runs
from .storage import ensure_dirs
from .tools import discover
from .tools.registry import all_tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("selfx.api")

API_PREFIX = "/api/v1"
RETENTION_INTERVAL_SECONDS = 3600
WORKFLOW_RECONCILE_INTERVAL_SECONDS = 15
_BOOTSTRAP_ADMIN_LOCK = 0x53656C66584144  # SelfXAD


def bootstrap_admin() -> None:
    """Create the initial admin account if the users table is empty (SPEC §3)."""
    with SessionLocal.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_ADMIN_LOCK})
        if db.scalar(select(User.id).limit(1)) is not None:
            return
        if not settings.debug and settings.selfx_admin_password.strip().lower() in ("", "change-me"):
            raise RuntimeError("Set SELFX_ADMIN_PASSWORD before creating the initial admin account.")
        db.add(
            User(
                username=settings.selfx_admin_user,
                password_hash=hash_password(settings.selfx_admin_password),
                is_admin=True,
            )
        )
    logger.info("bootstrap admin user '%s' created", settings.selfx_admin_user)


async def retention_loop() -> None:
    """Hourly retention task: expired files, old jobs, orphan tmp dirs (SPEC §10)."""
    while True:
        try:
            await asyncio.to_thread(run_cleanup)
        except Exception:
            logger.exception("retention cleanup pass failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


async def workflow_reconcile_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(reconcile_runs)
        except Exception:
            logger.exception("workflow reconciliation failed")
        await asyncio.sleep(WORKFLOW_RECONCILE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_secret_key()
    init_db()
    ensure_dirs()
    bootstrap_admin()
    discover()
    logger.info("SelfX API started with %d registered tool(s)", len(all_tools()))
    tasks = [
        asyncio.create_task(retention_loop()),
        asyncio.create_task(workflow_reconcile_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})


app = FastAPI(title="SelfX", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# prod is same-origin behind the nginx proxy; this only serves `npm run dev` (SPEC §10)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix=API_PREFIX)
app.include_router(tools_routes.router, prefix=API_PREFIX)
app.include_router(files_routes.router, prefix=API_PREFIX)
app.include_router(jobs_routes.router, prefix=API_PREFIX)
app.include_router(admin_routes.router, prefix=API_PREFIX)
app.include_router(kb_routes.router, prefix=API_PREFIX)
app.include_router(agent_routes.router, prefix=API_PREFIX)
app.include_router(models_routes.router, prefix=API_PREFIX)
app.include_router(presets_routes.router, prefix=API_PREFIX)
app.include_router(workflows_routes.router, prefix=API_PREFIX)


@app.get(API_PREFIX + "/healthz")
def healthz() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None
    try:
        redis_conn.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="redis unavailable") from None
    return {"status": "ok", "service": "selfx"}


# Optional: serve the built SPA from the API process itself when WEB_DIST points at a
# `dist` folder. In the Docker/compose setup nginx serves the SPA and WEB_DIST is unset,
# so this whole block is a no-op there.
_WEB_DIST = os.environ.get("WEB_DIST", "").strip()
if _WEB_DIST and Path(_WEB_DIST).is_dir():
    _web_root = Path(_WEB_DIST).resolve()
    _assets = _web_root / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (_web_root / full_path).resolve()
        if candidate.is_relative_to(_web_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_web_root / "index.html")

    logger.info("serving SPA from %s", _WEB_DIST)
