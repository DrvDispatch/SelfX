"""Natural-language agent API: POST /agent/chat drives SelfX's tools via a local
(Ollama) or cloud (Gemini) brain. Files stay local; the model sees only ids/summaries."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import core, gemini_agent, ollama_agent
from ..auth import get_current_user
from ..config import settings
from ..db import get_db
from ..models import User
from ..ratelimit import RATE_LIMIT, limiter

logger = logging.getLogger("selfx.routes.agent")
router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChat(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    file_ids: list[UUID] = Field(default_factory=list)
    provider: str | None = None  # "ollama" | "gemini"; defaults to server config


@router.get("/status")
def status_(user: User = Depends(get_current_user)) -> dict:
    return {
        "default_provider": settings.selfx_agent_provider,
        "gemini_available": gemini_agent.available(),
        "local_model": settings.ollama_model,
        "gemini_model": settings.gemini_model,
    }


@router.get("/tools")
def tools(user: User = Depends(get_current_user)) -> list[dict]:
    return [{"name": s["name"], "kind": s["kind"], "description": s["description"]} for s in core.build_specs()]


@router.post("/chat")
@limiter.limit(RATE_LIMIT)
def chat(
    request: Request,
    payload: AgentChat,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    provider = (payload.provider or settings.selfx_agent_provider or "ollama").lower()
    if provider == "gemini":
        if not gemini_agent.available():
            raise HTTPException(status_code=409, detail="Gemini is not configured (set GEMINI_API_KEY)")
        answer, steps = gemini_agent.run(db, user, payload.message, payload.file_ids)
    else:
        provider = "ollama"
        answer, steps = ollama_agent.run(db, user, payload.message, payload.file_ids)
    return {"answer": answer, "steps": steps, "provider": provider}
