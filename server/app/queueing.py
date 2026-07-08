"""RQ queues and job enqueueing (SPEC §1, §6)."""

import logging
import uuid

from redis import Redis
from rq import Queue

from .config import settings

logger = logging.getLogger("selfx.queueing")

QUEUE_NAMES = ("default", "heavy")

# Redis pub/sub channel the worker publishes job state to, and the SSE endpoint
# subscribes to for live progress (replaces client-side polling).
JOB_EVENTS_CHANNEL = "selfx:job-events"

redis_conn = Redis.from_url(settings.redis_url)

_queues: dict[str, Queue] = {}


def get_queue(name: str = "default") -> Queue:
    if name not in QUEUE_NAMES:
        name = "default"
    if name not in _queues:
        _queues[name] = Queue(name, connection=redis_conn)
    return _queues[name]


def enqueue_job(
    job_id: uuid.UUID | str,
    queue_name: str = "default",
    params: dict | None = None,
) -> str:
    """Enqueue app.worker.run_tool(job_id[, params]) on the given queue; returns the
    RQ job id. `params` carries the REAL (un-redacted) parameters to the worker as a
    job argument so secrets never have to be persisted in cleartext in the DB."""
    queue = get_queue(queue_name)
    call_args: list = [str(job_id)]
    if params is not None:
        call_args.append(params)
    rq_job = queue.enqueue(
        "app.worker.run_tool",
        *call_args,
        job_timeout=settings.job_timeout_seconds,
        result_ttl=3600,
        failure_ttl=86400,
        description=f"selfx job {job_id}",
    )
    logger.info("job %s enqueued on '%s' (rq id %s)", job_id, queue.name, rq_job.id)
    return rq_job.id


def enqueue_batch(job_id: uuid.UUID | str, tool_slug: str, queue_name: str = "default",
                  params: dict | None = None) -> str:
    """Enqueue app.worker.run_batch(job_id, tool_slug, params) — one tool over many files."""
    rq_job = get_queue(queue_name).enqueue(
        "app.worker.run_batch",
        str(job_id), tool_slug, params or {},
        job_timeout=settings.job_timeout_seconds,
        result_ttl=3600, failure_ttl=86400,
        description=f"selfx batch {job_id}",
    )
    return rq_job.id


def enqueue_pipeline(job_id: uuid.UUID | str, steps: list[dict], queue_name: str = "default") -> str:
    """Enqueue app.worker.run_pipeline(job_id, steps) — a linear chain of tools."""
    rq_job = get_queue(queue_name).enqueue(
        "app.worker.run_pipeline",
        str(job_id), steps,
        job_timeout=settings.job_timeout_seconds,
        result_ttl=3600, failure_ttl=86400,
        description=f"selfx pipeline {job_id}",
    )
    return rq_job.id


def enqueue_kb_ingest(document_id: uuid.UUID | str) -> str:
    """Enqueue knowledge-base ingestion of one document on the heavy queue."""
    rq_job = get_queue("heavy").enqueue(
        "app.kb.ingest.ingest_document",
        str(document_id),
        job_timeout=settings.job_timeout_seconds,
        result_ttl=600,
        failure_ttl=86400,
        description=f"kb ingest {document_id}",
    )
    logger.info("kb document %s ingest enqueued (rq id %s)", document_id, rq_job.id)
    return rq_job.id


def cancel_rq_job(rq_job_id: str) -> None:
    """Best-effort cancel of a queued RQ job."""
    try:
        from rq.job import Job as RQJob

        RQJob.fetch(rq_job_id, connection=redis_conn).cancel()
    except Exception:
        logger.warning("could not cancel rq job %s (may have already started)", rq_job_id)


def queue_depths() -> dict[str, int]:
    return {name: get_queue(name).count for name in QUEUE_NAMES}
