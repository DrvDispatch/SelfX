"""FastAPI app: routers, startup tasks, hourly retention loop, healthz (SPEC §5, §10)."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

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
from .routes import auth as auth_routes
from .routes import files as files_routes
from .routes import jobs as jobs_routes
from .routes import kb as kb_routes
from .routes import tools as tools_routes
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


def bootstrap_admin() -> None:
    """Create the initial admin account if the users table is empty (SPEC §3)."""
    with SessionLocal() as db:
        count = db.scalar(select(User.id).limit(1))
        if count is not None:
            return
        db.add(
            User(
                username=settings.selfx_admin_user,
                password_hash=hash_password(settings.selfx_admin_password),
                is_admin=True,
            )
        )
        db.commit()
        logger.info("bootstrap admin user '%s' created", settings.selfx_admin_user)


async def retention_loop() -> None:
    """Hourly retention task: expired files, old jobs, orphan tmp dirs (SPEC §10)."""
    while True:
        try:
            await asyncio.to_thread(run_cleanup)
        except Exception:
            logger.exception("retention cleanup pass failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_secret_key()
    init_db()
    try:
        from .kb.schema import ensure_schema as kb_ensure_schema

        kb_ensure_schema()
    except Exception:
        logger.exception("knowledge-base schema setup failed — KB features disabled")
    ensure_dirs()
    bootstrap_admin()
    discover()
    logger.info("SelfX API started with %d registered tool(s)", len(all_tools()))
    retention_task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task


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
    return {"status": "ok"}


# Optional: serve the built SPA from the API process itself when WEB_DIST points at a
# `dist` folder. In the Docker/compose setup nginx serves the SPA and WEB_DIST is unset,
# so this whole block is a no-op there.
_WEB_DIST = os.environ.get("WEB_DIST", "").strip()
if _WEB_DIST and os.path.isdir(_WEB_DIST):
    _assets = os.path.join(_WEB_DIST, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = os.path.normpath(os.path.join(_WEB_DIST, full_path))
        if candidate.startswith(_WEB_DIST) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_WEB_DIST, "index.html"))

    logger.info("serving SPA from %s", _WEB_DIST)
