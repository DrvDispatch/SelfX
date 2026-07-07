"""/admin/*: stats, user management, all-users job list (SPEC §5; admin only)."""

import logging
import shutil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import storage
from ..auth import hash_password, require_admin
from ..db import get_db
from ..models import File, Job, User
from ..queueing import queue_depths
from ..schemas import AdminStats, AdminUserCreate, AdminUserOut, AdminUserPatch, JobList
from .jobs import job_to_schema

logger = logging.getLogger("selfx.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStats)
def stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminStats:
    users = db.scalar(select(func.count()).select_from(User)) or 0
    jobs_total = db.scalar(select(func.count()).select_from(Job)) or 0
    by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    try:
        depths = queue_depths()
    except Exception:
        logger.exception("could not read queue depths")
        raise HTTPException(status_code=503, detail="redis unavailable") from None
    return AdminStats(
        users=users,
        jobs_total=jobs_total,
        jobs_by_status=by_status,
        disk_used_bytes=storage.disk_used_bytes(),
        queue_depth=depths,
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [AdminUserOut.model_validate(u) for u in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already taken")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("admin %s created user '%s' (admin=%s)", admin.username, user.username, user.is_admin)
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(
    user_id: UUID,
    payload: AdminUserPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.disabled is not None:
        user.disabled = payload.disabled
    db.commit()
    db.refresh(user)
    logger.info("admin %s updated user '%s'", admin.username, user.username)
    return AdminUserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="you cannot delete your own account")
    # cascade: the user's files (disk + rows), then jobs, then the user
    for f in db.scalars(select(File).where(File.user_id == user.id)).all():
        storage.delete_stored_file(f.stored_path)
        db.delete(f)
    for job in db.scalars(select(Job).where(Job.user_id == user.id)).all():
        shutil.rmtree(storage.outputs_dir(job.id), ignore_errors=True)
        db.delete(job)
    db.delete(user)
    db.commit()
    logger.info("admin %s deleted user '%s'", admin.username, user.username)


@router.get("/jobs", response_model=JobList)
def all_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> JobList:
    total = db.scalar(select(func.count()).select_from(Job)) or 0
    jobs = db.scalars(
        select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return JobList(items=[job_to_schema(j) for j in jobs], total=total)
