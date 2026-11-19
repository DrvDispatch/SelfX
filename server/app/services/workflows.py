"""Submission and queue reconciliation for transcript workflows.

The committed workflow run is the delivery record. Redis delivers attempts;
Postgres owns the run, its input reference, and its terminal state.
"""

import hashlib
import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from rq.exceptions import NoSuchJobError
from rq.job import Job as RqJob
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import File, Job, User, WorkflowRun, utcnow
from ..queueing import enqueue_workflow, redis_conn
from ..storage import file_abs_path
from ..tools.transcribe import Transcribe, _resolve_language
from ..tools.base import ToolError
from .jobs import matched_extension

logger = logging.getLogger("selfx.workflows")
TRANSCRIPT_WORKFLOW = "workflow:transcript-pdf"
ACTION_WORKFLOW = "workflow:actions"
WORKFLOW_TYPES = (TRANSCRIPT_WORKFLOW, ACTION_WORKFLOW)
HEARTBEAT_SECONDS = 10
TRANSCRIPT_CHECKPOINT = "transcript.json"
_STALE_AFTER = timedelta(seconds=90)
_FINISHED_TASK_STATES = {"failed", "finished", "stopped", "canceled"}
_TRANSCRIPT_PROMPT = re.compile(
    r"transcribe(?: (?:this|the|my) (?:audio|video|recording|mp4|file|clip))?"
    r"(?: (?:and|then|and then))? (?:into|put (?:the transcription|the transcript|it) into|"
    r"make|create|generate|export|save (?:the transcript|it) as|turn it into)"
    r" (?:me )?(?:a )?(?:timestamped )?pdf(?: (?:file|transcript))?"
    r"(?: (?:and|plus) (?:give me |create |export )?(?:an? )?(?:srt|subtitles)(?: (?:file|captions))?)?"
)


def supported_prompt(prompt: str) -> bool:
    normalized = " ".join(prompt.strip().lower().rstrip(".!?").replace(",", " ").split())
    return bool(_TRANSCRIPT_PROMPT.fullmatch(normalized))


def _task_id(job_id: UUID, attempt: int) -> str:
    return f"workflow-{job_id}-{attempt}"


def get_run(db: Session, job_id: UUID, *, lock: bool = False) -> tuple[Job, WorkflowRun] | None:
    query = select(Job, WorkflowRun).join(WorkflowRun, WorkflowRun.job_id == Job.id)
    query = query.where(Job.id == job_id, Job.tool.in_(WORKFLOW_TYPES))
    if lock:
        query = query.with_for_update(of=Job)
    row = db.execute(query).one_or_none()
    return (row[0], row[1]) if row else None


def get_owned_run(db: Session, user: User, job_id: UUID, *, lock: bool = False) -> tuple[Job, WorkflowRun]:
    record = get_run(db, job_id, lock=lock)
    if not record or record[0].user_id != user.id:
        raise HTTPException(404, "Workflow run not found")
    return record


def get_source(db: Session, user: User, file_id: UUID | None, *, lock: bool = False) -> File:
    if file_id is None:
        raise HTTPException(404, "The source file is no longer available")
    query = select(File).where(File.id == file_id, File.user_id == user.id)
    source = db.scalar(query.with_for_update() if lock else query)
    if source is None:
        raise HTTPException(404, "The source file is no longer available")
    if source.expires_at is not None and source.expires_at < utcnow():
        raise HTTPException(410, "The source file has expired")
    return source


def _existing_request(db: Session, user: User, key: str | None, digest: str) -> Job | None:
    if key is None:
        return None
    record = db.scalar(select(WorkflowRun).where(WorkflowRun.user_id == user.id, WorkflowRun.request_key == key))
    if record is None:
        return None
    if record.request_digest != digest:
        raise HTTPException(409, "This submission key already belongs to a different request")
    return db.get(Job, record.job_id)


def get_checkpoint(db: Session, job_id: UUID, *, lock: bool = False) -> File | None:
    query = select(File).where(
        File.job_id == job_id, File.kind == "output", File.orig_name == TRANSCRIPT_CHECKPOINT,
    )
    if lock:
        query = query.with_for_update()
    output = db.scalar(query)
    if output is None or (output.expires_at is not None and output.expires_at < utcnow()):
        return None
    return output if file_abs_path(output.stored_path).is_file() else None


def outputs_in_use(db: Session, job_id: UUID) -> bool:
    """Lock output assets before checking whether active workflows use them."""
    outputs = list(db.scalars(
        select(File.id).where(File.job_id == job_id, File.kind == "output").with_for_update()
    ))
    if not outputs:
        return False
    return db.scalar(
        select(WorkflowRun.job_id).join(Job, Job.id == WorkflowRun.job_id)
        .where(WorkflowRun.source_file_id.in_(outputs), Job.status.in_(("queued", "running")))
        .limit(1)
    ) is not None


def create_run(
    db: Session, user: User, file_id: UUID, language: str, title: str | None,
    prompt: str | None = None, key: str | None = None,
) -> Job:
    if prompt and not supported_prompt(prompt):
        raise HTTPException(422, "This workflow transcribes a recording and exports PDF and SRT. Try the example instruction.")
    try:
        language = _resolve_language(language) or "auto"
    except ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    title = title.strip() if title else None
    params = {"language": language}
    if title:
        params["title"] = title
    digest = _digest(TRANSCRIPT_WORKFLOW, file_id, params)
    existing = _existing_request(db, user, key, digest)
    if existing is not None:
        return existing

    source = get_source(db, user, file_id, lock=True)
    if not matched_extension(source.orig_name, Transcribe.accepts):
        raise HTTPException(422, "Choose a supported audio or video file")
    params.setdefault("title", Path(source.orig_name).stem[:160] or "Transcript")
    return _create_job(db, user, source, TRANSCRIPT_WORKFLOW, params, key, digest)


def validate_action_plan(plan: dict, source_name: str) -> dict:
    from .workflow_actions import validate_plan

    try:
        return validate_plan(plan, source_name)
    except ToolError as exc:
        raise HTTPException(422, str(exc)) from None


def create_action_run(
    db: Session, user: User, file_id: UUID, plan: dict, key: str | None = None,
) -> Job:
    digest = _digest(ACTION_WORKFLOW, file_id, plan)
    existing = _existing_request(db, user, key, digest)
    if existing is not None:
        return existing
    source = get_source(db, user, file_id, lock=True)
    validated = validate_action_plan(plan, source.orig_name)
    return _create_job(db, user, source, ACTION_WORKFLOW, {"plan": validated}, key, digest)


def _digest(tool: str, file_id: UUID, params: dict) -> str:
    return hashlib.sha256(json.dumps([tool, str(file_id), params], sort_keys=True).encode()).hexdigest()


def _create_job(
    db: Session, user: User, source: File, tool: str, params: dict, key: str | None, digest: str,
) -> Job:
    job_id = uuid4()
    job = Job(
        id=job_id, user_id=user.id, tool=tool, status="queued",
        message="Waiting for a worker", params=params, rq_job_id=_task_id(job_id, 1),
    )
    try:
        db.add(job)
        db.flush()
        db.add(WorkflowRun(
            job_id=job_id, user_id=user.id, source_file_id=source.id, request_key=key,
            request_digest=digest, attempt=1,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _existing_request(db, user, key, digest)
        if existing is not None:
            return existing
        raise
    return job


def retry_run(db: Session, user: User, job_id: UUID) -> Job:
    job, run = get_owned_run(db, user, job_id, lock=True)
    if job.status == "queued" or job.status == "running":
        return job  # A repeated request after a lost response keeps the active attempt.
    if job.status not in {"error", "canceled"}:
        raise HTTPException(409, "This workflow is already complete")
    if job.tool != TRANSCRIPT_WORKFLOW or get_checkpoint(db, job.id, lock=True) is None:
        get_source(db, user, run.source_file_id, lock=True)
    run.attempt += 1
    run.heartbeat_at = None
    job.status = "queued"
    job.progress = 0
    job.error = None
    job.started_at = None
    job.finished_at = None
    job.message = "Waiting for a worker"
    job.rq_job_id = _task_id(job.id, run.attempt)
    db.commit()
    return job


def mark_error(job: Job, message: str) -> None:
    job.status = "error"
    job.error = message[:2000]
    job.message = "Workflow interrupted" if job.started_at else "Workflow could not start"
    job.finished_at = utcnow()


def dispatch_run(job_id: UUID) -> None:
    """Deliver a committed queued attempt once while the database row is locked."""
    try:
        with SessionLocal.begin() as db:
            record = get_run(db, job_id, lock=True)
            if record is None:
                return
            job, run = record
            if job.status != "queued" or job.rq_job_id is None:
                return
            try:
                task = RqJob.fetch(job.rq_job_id, connection=redis_conn)
            except NoSuchJobError:
                enqueue_workflow(job.id, run.attempt, job.rq_job_id)
            else:
                if task.get_status(refresh=False) in _FINISHED_TASK_STATES:
                    mark_error(job, "The worker stopped before starting. Retry this workflow.")
    except Exception:
        logger.warning("workflow %s dispatch deferred", job_id, exc_info=True)


def reconcile_runs() -> None:
    """Redeliver queued runs after Redis loss and settle attempts without a heartbeat."""
    cutoff = utcnow() - _STALE_AFTER
    with SessionLocal.begin() as db:
        stale = db.execute(
            select(Job).join(WorkflowRun, WorkflowRun.job_id == Job.id)
            .where(Job.status == "running", WorkflowRun.heartbeat_at < cutoff)
            .limit(64).with_for_update(of=Job, skip_locked=True)
        ).scalars()
        for job in stale:
            heartbeat = db.scalar(select(WorkflowRun.heartbeat_at).where(WorkflowRun.job_id == job.id))
            if heartbeat is not None and heartbeat < cutoff:
                mark_error(job, "The worker stopped responding. Retry this workflow to resume.")
        queued_ids = list(db.scalars(
            select(Job.id).join(WorkflowRun, WorkflowRun.job_id == Job.id)
            .where(Job.status == "queued").order_by(Job.created_at).limit(64)
        ))
    for job_id in queued_ids:
        dispatch_run(job_id)
