"""Admin: manage local Ollama models (list / pull / delete) via the Ollama API."""

import logging
import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..auth import get_current_user, require_admin
from ..config import settings
from ..models import User
from ..services.runtime_probe import probe_hardware

logger = logging.getLogger("selfx.routes.models")
router = APIRouter(prefix="/admin/models", tags=["models"])

_pulling: set[str] = set()  # models currently being pulled (background threads)


def _admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user


@router.get("")
def list_models(user: User = Depends(_admin)) -> dict:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5.0)
        r.raise_for_status()
        return {"models": r.json().get("models", []), "pulling": sorted(_pulling)}
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama is not reachable") from None


@router.get("/hardware", dependencies=[Depends(require_admin)])
def hardware(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return probe_hardware()


class PullReq(BaseModel):
    name: str = Field(min_length=1, max_length=128)


def _do_pull(name: str) -> None:
    try:
        with httpx.stream("POST", f"{settings.ollama_url}/api/pull", json={"name": name}, timeout=None) as r:
            for _ in r.iter_lines():
                pass
        logger.info("model pull complete: %s", name)
    except Exception:
        logger.exception("model pull failed: %s", name)
    finally:
        _pulling.discard(name)


@router.post("/pull")
def pull_model(req: PullReq, user: User = Depends(_admin)) -> dict:
    name = req.name.strip()
    if name not in _pulling:
        _pulling.add(name)
        threading.Thread(target=_do_pull, args=(name,), daemon=True).start()
    return {"status": "pulling", "name": name}


@router.delete("/{name:path}")
def delete_model(name: str, user: User = Depends(_admin)) -> dict:
    try:
        r = httpx.request("DELETE", f"{settings.ollama_url}/api/delete", json={"name": name}, timeout=10.0)
        if r.status_code >= 400:
            raise HTTPException(status_code=400, detail="could not delete that model")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Ollama is not reachable") from None
    return {"deleted": name}
