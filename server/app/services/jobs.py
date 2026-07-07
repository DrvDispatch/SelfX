"""Shared job creation: validate (ownership/availability/extension/MIME/params) →
persist (redacted params) → enqueue (real params). Used by both routes/jobs.py and
the NL agent so neither can bypass the gates."""

import logging
from uuid import UUID

import jsonschema
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import File, Job, User, utcnow
from ..queueing import enqueue_job
from ..tools.base import Tool
from ..tools.registry import get_tool

logger = logging.getLogger("selfx.services.jobs")

# extension → allowed sniffed MIMEs; mismatch is rejected for archives (SPEC §10)
ARCHIVE_MIMES: dict[str, set[str]] = {
    ".zip": {"application/zip", "application/x-zip-compressed"},
    ".7z": {"application/x-7z-compressed"},
    ".tar": {"application/x-tar"},
    ".gz": {"application/gzip", "application/x-gzip"},
    ".tgz": {"application/gzip", "application/x-gzip"},
    ".tar.gz": {"application/gzip", "application/x-gzip"},
}


def redact_params(params: dict) -> dict:
    """Replace any param whose key contains 'password' with '***' for DB persistence."""
    return {k: ("***" if "password" in k.lower() else v) for k, v in (params or {}).items()}


def matched_extension(name: str, accepts: list[str]) -> str | None:
    lowered = name.lower()
    for ext in sorted(accepts, key=len, reverse=True):  # ".tar.gz" before ".gz"
        if lowered.endswith(ext.lower()):
            return ext.lower()
    return None


def validate_files(db: Session, user: User, tool: Tool, file_ids: list[UUID]) -> list[File]:
    if len(set(file_ids)) != len(file_ids):
        raise HTTPException(status_code=400, detail="duplicate file ids in request")
    # min_files == 0 means the tool takes no files; empty accepts w/ min_files>=1 = any type
    if tool.min_files == 0:
        if file_ids:
            raise HTTPException(status_code=400, detail="this tool does not take input files")
        return []
    if len(file_ids) < tool.min_files:
        raise HTTPException(status_code=400, detail=f"this tool requires at least {tool.min_files} input file(s)")
    if not tool.multi_file and len(file_ids) > 1:
        raise HTTPException(status_code=400, detail="this tool accepts a single input file")

    files: list[File] = []
    for fid in file_ids:
        f = db.get(File, fid)
        if f is None or (f.user_id != user.id and not user.is_admin):
            raise HTTPException(status_code=404, detail=f"file {fid} not found")
        if f.kind != "upload":
            raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' is not an upload")
        if f.job_id is not None:
            raise HTTPException(status_code=409, detail=f"file '{f.orig_name}' is already used by another job")
        if f.expires_at is not None and f.expires_at < utcnow():
            raise HTTPException(status_code=400, detail=f"file '{f.orig_name}' has expired")
        if tool.accepts:
            ext = matched_extension(f.orig_name, tool.accepts)
            if ext is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"file '{f.orig_name}' is not accepted by this tool (expects: {', '.join(tool.accepts)})",
                )
            allowed = ARCHIVE_MIMES.get(ext)
            if allowed and f.mime not in allowed:
                raise HTTPException(status_code=422, detail=f"file '{f.orig_name}' content does not match its archive extension")
        files.append(f)
    return files


def create_and_run_job(db: Session, user: User, tool_slug: str, file_ids: list[UUID], params: dict) -> Job:
    """The single validated path to create + enqueue a job. Raises HTTPException on any
    gate failure (routes propagate it; the agent catches it and tells the model)."""
    tool = get_tool(tool_slug)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool '{tool_slug}'")
    try:
        available, reason = tool.available()
    except Exception:
        logger.exception("availability check failed for tool '%s'", tool.slug)
        available, reason = False, "availability check failed"
    if not available:
        raise HTTPException(status_code=409, detail=f"tool unavailable: {reason or 'unknown'}")

    files = validate_files(db, user, tool, file_ids)
    try:
        jsonschema.validate(instance=params or {}, schema=tool.params_schema)
    except jsonschema.ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid params: {exc.message}") from None

    job = Job(user_id=user.id, tool=tool.slug, status="queued", params=redact_params(params or {}))
    db.add(job)
    db.flush()
    for f in files:
        f.job_id = job.id
    db.commit()
    try:
        job.rq_job_id = enqueue_job(job.id, tool.queue, params or {})
        db.commit()
    except Exception:
        logger.exception("failed to enqueue job %s", job.id)
        job.status = "error"
        job.error = "job queue unavailable — please retry later"
        job.finished_at = utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="job queue unavailable") from None
    logger.info("job %s created (tool=%s) by %s", job.id, tool.slug, user.username)
    db.refresh(job)
    return job
