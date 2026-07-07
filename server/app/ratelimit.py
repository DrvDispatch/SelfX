"""slowapi rate limiter with per-user key (fallback: client IP) — SPEC §10."""

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from .config import settings


def user_or_ip_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, settings.selfx_secret_key, algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.InvalidTokenError:
            pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=user_or_ip_key,
    storage_uri=settings.redis_url,
    swallow_errors=True,  # if redis is briefly down, do not 500 on rate-limit lookups
)

RATE_LIMIT = f"{settings.rate_limit_per_minute}/minute"
