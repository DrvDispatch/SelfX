"""Authenticated workflow planning, submission, and status."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import File, User
from ..ratelimit import RATE_LIMIT, limiter
from ..schemas import JobOut
from ..services import workflows
from .jobs import job_to_schema

router = APIRouter(prefix="/workflow-runs", tags=["workflows"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


class WorkflowCreate(BaseModel):
    file_id: UUID
    language: str = Field(default="auto", min_length=1, max_length=10)
    title: str | None = Field(default=None, max_length=160)
    prompt: str | None = Field(default=None, max_length=500)


class PlanRequest(BaseModel):
    file_id: UUID
    prompt: str = Field(min_length=1, max_length=500)


class PlanSubmit(BaseModel):
    file_id: UUID
    plan: dict


@router.get("/catalog")
def workflow_catalog(user: CurrentUser, db: DbSession) -> list[dict]:
    from ..services.workflow_actions import action_catalog

    db.close()
    return action_catalog()


@router.get("/planner")
async def planner_status(user: CurrentUser, db: DbSession) -> dict:
    from ..services.workflow_planner import planner_status as local_planner_status

    await run_in_threadpool(db.close)
    return await local_planner_status()


@router.post("/plan")
@limiter.limit("12/minute")
async def propose_plan(
    request: Request,
    payload: PlanRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict:
    from ..services.workflow_actions import action_catalog
    from ..services.workflow_planner import plan_prompt

    try:
        source = await run_in_threadpool(workflows.get_source, db, user, payload.file_id)
        input_name, mime = source.orig_name, source.mime
    finally:
        await run_in_threadpool(db.close)
    source_type = f"{mime} ({Path(input_name).suffix.lower()})"
    actions = await run_in_threadpool(action_catalog)
    proposal = await plan_prompt(payload.prompt, source_type, actions)
    return await run_in_threadpool(workflows.validate_action_plan, proposal, input_name)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
@limiter.limit(RATE_LIMIT)
def create_run(
    request: Request,
    payload: WorkflowCreate,
    background: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
    request_key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)] = None,
) -> JobOut:
    job = workflows.create_run(db, user, payload.file_id, payload.language, payload.title, payload.prompt, request_key)
    result = job_to_schema(job, db.get(File, payload.file_id))
    db.close()
    background.add_task(workflows.dispatch_run, job.id)
    return result


@router.post("/execute", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
@limiter.limit(RATE_LIMIT)
def execute_plan(
    request: Request,
    payload: PlanSubmit,
    background: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
    request_key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)] = None,
) -> JobOut:
    job = workflows.create_action_run(db, user, payload.file_id, payload.plan, request_key)
    result = job_to_schema(job, db.get(File, payload.file_id))
    db.close()
    background.add_task(workflows.dispatch_run, job.id)
    return result


@router.get("/{job_id}", response_model=JobOut)
def get_run(
    job_id: UUID, user: CurrentUser, db: DbSession,
) -> JobOut:
    job, run = workflows.get_owned_run(db, user, job_id)
    source = db.get(File, run.source_file_id) if run.source_file_id else None
    return job_to_schema(job, source)


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
@limiter.limit(RATE_LIMIT)
def retry_run(
    request: Request,
    job_id: UUID,
    background: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
) -> JobOut:
    job = workflows.retry_run(db, user, job_id)
    _, run = workflows.get_owned_run(db, user, job_id)
    source = db.get(File, run.source_file_id) if run.source_file_id else None
    result = job_to_schema(job, source)
    db.close()
    background.add_task(workflows.dispatch_run, job.id)
    return result
