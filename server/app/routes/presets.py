"""User-scoped presets: save a tool + parameter set to re-run later (power-user)."""

import logging
from datetime import datetime
from uuid import UUID

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Preset, User
from ..ratelimit import RATE_LIMIT, limiter
from ..tools.registry import get_tool

logger = logging.getLogger("selfx.routes.presets")

router = APIRouter(prefix="/presets", tags=["presets"])


def _strip_secrets(params: dict) -> dict:
    """Drop password-bearing keys entirely — a preset must never persist a secret.
    The user re-enters those fields when they apply the preset."""
    return {k: v for k, v in (params or {}).items() if "password" not in k.lower()}


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tool: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


class PresetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    tool: str
    params: dict
    created_at: datetime


@router.get("", response_model=list[PresetOut])
def list_presets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Preset]:
    rows = db.scalars(
        select(Preset).where(Preset.user_id == user.id).order_by(Preset.created_at.desc())
    ).all()
    return list(rows)


@router.post("", response_model=PresetOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT)
def create_preset(
    request: Request,
    payload: PresetCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Preset:
    tool = get_tool(payload.tool)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool '{payload.tool}'")
    # Validate the raw params first (catches genuinely invalid values), then strip any
    # secrets and re-validate: a preset must never store a password, and if a required
    # field IS a secret the preset would be broken, so reject it with a clear message.
    try:
        jsonschema.validate(instance=payload.params or {}, schema=tool.params_schema)
    except jsonschema.ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid params: {exc.message}") from None
    stored_params = _strip_secrets(payload.params or {})
    try:
        jsonschema.validate(instance=stored_params, schema=tool.params_schema)
    except jsonschema.ValidationError:
        raise HTTPException(
            status_code=422,
            detail="this tool needs a password each time it runs, so it can't be saved as a preset",
        ) from None

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    existing = db.scalar(
        select(Preset).where(Preset.user_id == user.id, Preset.name == name)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="a preset with that name already exists")

    preset = Preset(user_id=user.id, name=name, tool=tool.slug, params=stored_params)
    db.add(preset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="a preset with that name already exists") from None
    db.refresh(preset)
    logger.info("preset '%s' (%s) saved by %s", name, tool.slug, user.username)
    return preset


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(
    preset_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    preset = db.get(Preset, preset_id)
    if preset is None or (preset.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="preset not found")
    db.delete(preset)
    db.commit()
