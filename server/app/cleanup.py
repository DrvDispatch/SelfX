"""Retention: purge expired files, jobs older than 30 days, orphaned tmp dirs (SPEC §10)."""

import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from . import storage
from .db import SessionLocal
from .models import File, Job, WorkflowRun
from .services.workflows import outputs_in_use

logger = logging.getLogger("selfx.cleanup")

JOB_MAX_AGE_DAYS = 30
ACTIVE_STATUSES = ("queued", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def purge_expired_files(db: Session) -> int:
    now = _utcnow()
    active_input = exists(
        select(WorkflowRun.job_id).join(Job).where(
            WorkflowRun.source_file_id == File.id,
            Job.status.in_(ACTIVE_STATUSES),
        )
    )
    expired = db.scalars(
        select(File).where(File.expires_at < now, ~active_input).with_for_update(skip_locked=True)
    ).all()
    removed = 0
    for f in expired:
        if f.job_id is not None:
            job = db.get(Job, f.job_id)
            if job is not None and job.status in ACTIVE_STATUSES:
                continue  # never yank files out from under a queued/running job
        storage.delete_stored_file(f.stored_path)
        db.delete(f)
        removed += 1
    db.commit()
    return removed


def purge_old_jobs(db: Session) -> int:
    cutoff = _utcnow() - timedelta(days=JOB_MAX_AGE_DAYS)
    old_jobs = (
        db.query(Job)
        .filter(Job.created_at < cutoff, Job.status.not_in(ACTIVE_STATUSES))
        .with_for_update(skip_locked=True)
        .all()
    )
    removed = 0
    for job in old_jobs:
        if outputs_in_use(db, job.id):
            continue
        for f in list(job.files):
            if f.kind == "output":
                storage.delete_stored_file(f.stored_path)
                db.delete(f)
            else:
                f.job_id = None
        shutil.rmtree(storage.outputs_dir(job.id), ignore_errors=True)
        db.delete(job)
        removed += 1
    db.commit()
    return removed


def purge_orphan_tmp(db: Session) -> int:
    tmp_root = storage.data_dir() / "tmp"
    if not tmp_root.is_dir():
        return 0
    removed = 0
    for entry in tmp_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            job_id = uuid.UUID(entry.name)
        except ValueError:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
            continue
        job = db.get(Job, job_id)
        if job is None or job.status not in ACTIVE_STATUSES:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def run_cleanup() -> None:
    """One retention pass; called hourly from the api process (SPEC §10)."""
    with SessionLocal() as db:
        files_removed = purge_expired_files(db)
        jobs_removed = purge_old_jobs(db)
        tmp_removed = purge_orphan_tmp(db)
    if files_removed or jobs_removed or tmp_removed:
        logger.info(
            "cleanup: %d expired file(s), %d old job(s), %d orphan tmp dir(s) removed",
            files_removed,
            jobs_removed,
            tmp_removed,
        )
