"""Jobs CRUD: create/validate/enqueue, list, get, cancel, delete (SPEC §5)."""

import logging
import shutil
from uuid import UUID

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import storage
from ..auth import get_current_user
from ..db import get_db
from ..models import File, Job, User, utcnow
from ..queueing import cancel_rq_job, enqueue_batch, enqueue_job, enqueue_pipeline
from ..ratelimit import RATE_LIMIT, limiter
from ..schemas import FileInfo, JobCreate, JobList, JobOut
from ..services.jobs import create_and_run_job
from ..tools.base import Tool
from ..tools.registry import get_tool

logger = logging.getLogger("selfx.routes.jobs")

router = APIRouter(prefix="/jobs", tags=["jobs"])

# extension → allowed sniffed mimes; mismatch is rejected for archives (SPEC §10)
ARCHIVE_MIMES: dict[str, set[str]] = {
    ".zip": {"application/zip", "application/x-zip-compressed"},
    ".7z": {"application/x-7z-compressed"},
    ".tar": {"application/x-tar"},
    ".gz": {"application/gzip", "application/x-gzip"},
    ".tgz": {"application/gzip", "application/x-gzip"},
    ".tar.gz": {"application/gzip", "application/x-gzip"},
}


def job_to_schema(job: Job) -> JobOut:
    inputs = sorted((f for f in job.files if f.kind == "upload"), key=lambda f: f.created_at)
    outputs = sorted((f for f in job.files if f.kind == "output"), key=lambda f: f.orig_name)
    return JobOut(
        id=job.id,
        tool=job.tool,
        status=job.status,
        progress=job.progress,
        message=job.message,
        params=job.params or {},
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        input_files=[FileInfo.model_validate(f) for f in inputs],
        output_files=[FileInfo.model_validate(f) for f in outputs],
    )


def get_owned_job(job_id: UUID, user: User, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if job.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your job")
    return job


def _redact_params(params: dict | None) -> dict:
    """Return a shallow copy with any value whose KEY contains 'password' replaced
    by '***'. The redacted copy is what we persist in the jobs table (JSONB); the
    real params are handed straight to the worker via the queue instead."""
    if not params:
        return {}
    redacted: dict = {}
    for key, value in params.items():
        if isinstance(key, str) and "password" in key.lower():
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _matched_extension(name: str, accepts: list[str]) -> str | None:
    lowered = name.lower()
    for ext in sorted(accepts, key=len, reverse=True):  # match ".tar.gz" before ".gz"
        if lowered.endswith(ext.lower()):
            return ext.lower()
    return None


def _validate_files(payload: JobCreate, tool: Tool, user: User, db: Session) -> list[File]:
    if len(set(payload.file_ids)) != len(payload.file_ids):
        raise HTTPException(status_code=400, detail="duplicate file ids in request")
    # A tool takes no files only when min_files == 0 (e.g. qr-generate). An empty
    # `accepts` with min_files >= 1 means "any file type" (e.g. archive-compress).
    if tool.min_files == 0:
        if payload.file_ids:
            raise HTTPException(status_code=400, detail="this tool does not take input files")
        return []
    if len(payload.file_ids) < tool.min_files:
        raise HTTPException(
            status_code=400, detail=f"this tool requires at least {tool.min_files} input file(s)"
        )
    if not tool.multi_file and len(payload.file_ids) > 1:
        raise HTTPException(status_code=400, detail="this tool accepts a single input file")

    files: list[File] = []
    for fid in payload.file_ids:
        f = db.get(File, fid)
        if f is None or (f.user_id != user.id and not user.is_admin):
            raise HTTPException(status_code=404, detail=f"file {fid} not found")
        if f.kind != "upload":
            raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' is not an upload")
        if f.job_id is not None:
            raise HTTPException(
                status_code=409, detail=f"file '{f.orig_name}' is already used by another job"
            )
        if f.expires_at is not None and f.expires_at < utcnow():
            raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' has expired")
        # empty accepts == any file type (e.g. archive-compress): skip extension gate
        if tool.accepts:
            ext = _matched_extension(f.orig_name, tool.accepts)
            if ext is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"file '{f.orig_name}' is not accepted by this tool "
                    f"(expects: {', '.join(tool.accepts)})",
                )
            allowed_mimes = ARCHIVE_MIMES.get(ext)
            if allowed_mimes and f.mime not in allowed_mimes:
                logger.warning(
                    "mime mismatch rejected: file=%s ext=%s sniffed=%s", f.id, ext, f.mime
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"file '{f.orig_name}' content does not match its archive extension",
                )
        files.append(f)
    return files


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT)
def create_job(
    request: Request,
    payload: JobCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    # single validated choke-point shared with the NL agent
    job = create_and_run_job(db, user, payload.tool, payload.file_ids, payload.params)
    return job_to_schema(job)


class BatchCreate(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    file_ids: list[UUID] = Field(min_length=1)
    params: dict = Field(default_factory=dict)


@router.post("/batch", response_model=JobOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT)
def create_batch(
    request: Request,
    payload: BatchCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    """Run one single-file tool over many files, zipping the per-file outputs."""
    tool = get_tool(payload.tool)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool '{payload.tool}'")
    if tool.min_files != 1 or tool.multi_file:
        raise HTTPException(status_code=400, detail="batch supports single-file tools only")
    try:
        available, reason = tool.available()
    except Exception:
        available, reason = False, "availability check failed"
    if not available:
        raise HTTPException(status_code=409, detail=f"tool unavailable: {reason or 'unknown'}")

    if len(set(payload.file_ids)) != len(payload.file_ids):
        raise HTTPException(status_code=400, detail="duplicate file ids")
    files: list[File] = []
    for fid in payload.file_ids:
        f = db.get(File, fid)
        if f is None or (f.user_id != user.id and not user.is_admin) or f.kind != "upload":
            raise HTTPException(status_code=404, detail=f"file {fid} not found")
        if f.job_id is not None:
            raise HTTPException(status_code=409, detail=f"file '{f.orig_name}' is already used by another job")
        if f.expires_at is not None and f.expires_at < utcnow():
            raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' has expired")
        if tool.accepts:
            ext = _matched_extension(f.orig_name, tool.accepts)
            if ext is None:
                raise HTTPException(status_code=422, detail=f"file '{f.orig_name}' is not accepted by this tool")
            allowed = ARCHIVE_MIMES.get(ext)
            if allowed and f.mime not in allowed:
                raise HTTPException(status_code=422, detail=f"file '{f.orig_name}' content does not match its extension")
        files.append(f)

    try:
        jsonschema.validate(instance=payload.params or {}, schema=tool.params_schema)
    except jsonschema.ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid params: {exc.message}") from None

    job = Job(user_id=user.id, tool=f"batch:{tool.slug}", status="queued", params=_redact_params(payload.params or {}))
    db.add(job)
    db.flush()
    for f in files:
        f.job_id = job.id
    db.commit()
    try:
        job.rq_job_id = enqueue_batch(job.id, tool.slug, tool.queue, payload.params or {})
        db.commit()
    except Exception:
        logger.exception("failed to enqueue batch %s", job.id)
        job.status = "error"
        job.error = "job queue unavailable"
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="job queue unavailable") from None
    logger.info("batch job %s (%s x%d) by %s", job.id, tool.slug, len(files), user.username)
    db.refresh(job)
    return job_to_schema(job)


class PipelineStep(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


class PipelineCreate(BaseModel):
    steps: list[PipelineStep] = Field(min_length=1, max_length=12)
    file_ids: list[UUID] = Field(min_length=1, max_length=1)


@router.post("/pipeline", response_model=JobOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT)
def create_pipeline(
    request: Request,
    payload: PipelineCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    """Run a linear chain of single-file tools; each step's output feeds the next."""
    # Resolve + validate every step up front so a bad chain fails before it runs.
    resolved: list[Tool] = []
    for i, step in enumerate(payload.steps):
        tool = get_tool(step.tool)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"step {i + 1}: unknown tool '{step.tool}'")
        if tool.min_files != 1 or tool.multi_file:
            raise HTTPException(
                status_code=400,
                detail=f"step {i + 1} ('{tool.name}'): pipelines only support single-file tools",
            )
        try:
            available, reason = tool.available()
        except Exception:
            available, reason = False, "availability check failed"
        if not available:
            raise HTTPException(status_code=409, detail=f"step {i + 1} ('{tool.name}') unavailable: {reason or 'unknown'}")
        try:
            jsonschema.validate(instance=step.params or {}, schema=tool.params_schema)
        except jsonschema.ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"step {i + 1}: invalid params: {exc.message}") from None
        resolved.append(tool)

    # Validate the single input file against the FIRST step's accepts.
    fid = payload.file_ids[0]
    f = db.get(File, fid)
    if f is None or (f.user_id != user.id and not user.is_admin) or f.kind != "upload":
        raise HTTPException(status_code=404, detail=f"file {fid} not found")
    if f.job_id is not None:
        raise HTTPException(status_code=409, detail=f"file '{f.orig_name}' is already used by another job")
    if f.expires_at is not None and f.expires_at < utcnow():
        raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' has expired")
    first = resolved[0]
    if first.accepts:
        ext = _matched_extension(f.orig_name, first.accepts)
        if ext is None:
            raise HTTPException(
                status_code=422,
                detail=f"file '{f.orig_name}' is not accepted by the first step ('{first.name}')",
            )
        allowed = ARCHIVE_MIMES.get(ext)
        if allowed and f.mime not in allowed:
            raise HTTPException(status_code=422, detail=f"file '{f.orig_name}' content does not match its extension")

    # Real steps go to the worker; a password-redacted copy is persisted for display.
    real_steps = [{"tool": s.tool, "params": s.params or {}} for s in payload.steps]
    redacted_steps = [{"tool": s.tool, "params": _redact_params(s.params or {})} for s in payload.steps]
    queue = "heavy" if any(t.queue == "heavy" for t in resolved) else "default"

    labels = "→".join(t.slug for t in resolved)
    job = Job(user_id=user.id, tool=f"pipeline:{labels}"[:255], status="queued",
              params={"steps": redacted_steps})
    db.add(job)
    db.flush()
    f.job_id = job.id
    db.commit()
    try:
        job.rq_job_id = enqueue_pipeline(job.id, real_steps, queue)
        db.commit()
    except Exception:
        logger.exception("failed to enqueue pipeline %s", job.id)
        job.status = "error"
        job.error = "job queue unavailable"
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="job queue unavailable") from None
    logger.info("pipeline job %s (%d steps) by %s", job.id, len(resolved), user.username)
    db.refresh(job)
    return job_to_schema(job)


@router.get("", response_model=JobList)
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobList:
    total = db.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id)) or 0
    jobs = (
        db.scalars(
            select(Job)
            .where(Job.user_id == user.id)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return JobList(items=[job_to_schema(j) for j in jobs], total=total)


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    return job_to_schema(get_owned_job(job_id, user, db))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    job = get_owned_job(job_id, user, db)
    if job.status != "queued":
        raise HTTPException(
            status_code=409, detail=f"only queued jobs can be canceled (status: {job.status})"
        )
    if job.rq_job_id:
        cancel_rq_job(job.rq_job_id)
    job.status = "canceled"
    job.message = "canceled by user"
    job.finished_at = utcnow()
    db.commit()
    logger.info("job %s -> canceled by %s", job.id, user.username)
    return job_to_schema(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    job = get_owned_job(job_id, user, db)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="cannot delete a running job")
    for f in list(job.files):
        if f.kind == "output":
            storage.delete_stored_file(f.stored_path)
            db.delete(f)
        else:
            f.job_id = None  # keep the upload row, detach it from the job
    shutil.rmtree(storage.outputs_dir(job.id), ignore_errors=True)
    db.delete(job)
    db.commit()
    logger.info("job %s deleted by %s", job_id, user.username)
