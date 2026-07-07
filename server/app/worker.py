"""RQ worker entrypoint (`python -m app.worker`) and run_tool(job_id) — SPEC §6."""

import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from redis import Redis
from rq import Queue, Worker

from .config import settings
from .db import SessionLocal, init_db
from .models import File, Job
from .storage import ensure_dirs, file_abs_path, outputs_dir, sniff_mime_file, tmp_dir
from .tools import discover
from .tools.base import ToolContext, ToolError
from .tools.registry import get_tool

logger = logging.getLogger("selfx.worker")

# RQ imports this module by dotted path; make sure adapters are registered.
discover()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _set_progress(job_id: UUID, fraction: float, message: str = "") -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.progress = fraction
        if message:
            job.message = message[:512]
        db.commit()


def _mark_failed(job_id: UUID, message: str) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status = "error"
            job.error = message[:2000]
            job.finished_at = _utcnow()
            db.commit()
            logger.info("job %s -> error: %s", job_id, message)
    except Exception:
        logger.exception("could not mark job %s as failed", job_id)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _nice_stem(name: str) -> str:
    stem = _UNSAFE.sub("_", Path(name).stem).strip("._")
    return (stem or "output")[:80]


def _rename_outputs(out_dir: Path, input_files: list[File]) -> None:
    """Rename outputs named after the internal uuid input stem back to the user's
    original filename stem, so downloads are friendly (e.g. invoice-compressed.pdf)."""
    mapping: dict[str, str] = {}
    for f in input_files:
        uuid_stem = Path(f.stored_path).stem
        nice = _nice_stem(f.orig_name)
        if uuid_stem and nice and uuid_stem != nice:
            mapping[uuid_stem] = nice
    if not mapping:
        return
    for p in list(out_dir.rglob("*")):
        if not p.is_file():
            continue
        for uuid_stem, nice in mapping.items():
            if p.name.startswith(uuid_stem):
                target = p.with_name(nice + p.name[len(uuid_stem):])
                if target != p and not target.exists():
                    try:
                        p.rename(target)
                    except OSError:
                        pass
                break


def _register_outputs(db, job: Job) -> int:
    out_dir = outputs_dir(job.id)
    expires = None
    if settings.file_retention_hours > 0:
        expires = _utcnow() + timedelta(hours=settings.file_retention_hours)
    count = 0
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        db.add(
            File(
                user_id=job.user_id,
                job_id=job.id,
                kind="output",
                orig_name=path.name[:255],
                stored_path=path.relative_to(settings.data_dir).as_posix(),
                size=path.stat().st_size,
                mime=sniff_mime_file(path),
                expires_at=expires,
            )
        )
        count += 1
    return count


def run_tool(job_id: str) -> None:
    """Execute one job: queued -> running -> done/error, wiping the workdir in finally."""
    jid = UUID(str(job_id))
    workdir = None
    try:
        with SessionLocal() as db:
            job = db.get(Job, jid)
            if job is None:
                logger.error("job %s not found in database, skipping", jid)
                return
            if job.status != "queued":
                logger.info("job %s has status '%s', not running it", jid, job.status)
                return
            job.status = "running"
            job.started_at = _utcnow()
            job.message = "starting"
            db.commit()
            logger.info("job %s -> running (tool=%s)", jid, job.tool)

            tool = get_tool(job.tool)
            if tool is None:
                raise ToolError(f"unknown tool '{job.tool}'")

            inputs = (
                db.query(File)
                .filter(File.job_id == jid, File.kind == "upload")
                .order_by(File.created_at)
                .all()
            )
            input_paths = []
            for f in inputs:
                path = file_abs_path(f.stored_path)
                if not path.is_file():
                    raise ToolError("an input file is no longer available (it may have expired)")
                input_paths.append(path)

            workdir = tmp_dir(jid)
            workdir.mkdir(parents=True, exist_ok=True)
            out_dir = outputs_dir(jid)
            out_dir.mkdir(parents=True, exist_ok=True)

            ctx = ToolContext(
                job_id=jid,
                input_paths=input_paths,
                params=dict(job.params or {}),
                workdir=workdir,
                output_dir=out_dir,
                progress_cb=lambda fraction, message="": _set_progress(jid, fraction, message),
            )
            tool.run(ctx)

            _rename_outputs(out_dir, inputs)
            n_outputs = _register_outputs(db, job)
            job.status = "done"
            job.progress = 1.0
            job.finished_at = _utcnow()
            db.commit()
            logger.info("job %s -> done (%d output file(s))", jid, n_outputs)
    except ToolError as exc:
        logger.error("job %s tool error: %s", jid, exc, exc_info=True)
        _mark_failed(jid, str(exc))
    except Exception as exc:
        logger.exception("job %s crashed", jid)
        if "Timeout" in type(exc).__name__:
            _mark_failed(jid, f"job exceeded the time limit of {settings.job_timeout_seconds} seconds")
        else:
            _mark_failed(jid, "internal error while running the tool")
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    ensure_dirs()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in ("default", "heavy")]
    logger.info("SelfX worker starting, consuming queues: default, heavy")
    Worker(queues, connection=connection).work()


if __name__ == "__main__":
    main()
