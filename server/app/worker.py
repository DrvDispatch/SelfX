"""RQ worker entrypoint (`python -m app.worker`) and run_tool(job_id) — SPEC §6."""

import json
import logging
import re
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from redis import Redis
from rq import Queue, Worker

from .config import settings
from .db import SessionLocal, init_db
from .models import File, Job
from .queueing import JOB_EVENTS_CHANNEL, redis_conn
from .storage import ensure_dirs, file_abs_path, outputs_dir, sniff_mime_file, tmp_dir
from .tools import discover
from .tools.base import ToolContext, ToolError
from .tools.registry import get_tool

logger = logging.getLogger("selfx.worker")


def _publish_job(job: Job) -> None:
    """Best-effort push of a job's current state to the SSE channel (live progress)."""
    try:
        redis_conn.publish(JOB_EVENTS_CHANNEL, json.dumps({
            "id": str(job.id),
            "user_id": str(job.user_id),
            "tool": job.tool,
            "status": job.status,
            "progress": job.progress,
            "message": job.message,
        }))
    except Exception:
        pass  # streaming is best-effort; the poll fallback still reconciles

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
        _publish_job(job)


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
            _publish_job(job)
            logger.info("job %s -> error: %s", job_id, message)
    except Exception:
        logger.exception("could not mark job %s as failed", job_id)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Multi-part extensions that Path.suffix/Path.stem would split incorrectly.
_COMPOUND_SUFFIXES = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tar.zst",
    ".tar.lz",
    ".tar.lzma",
    ".tar.z",
)


def _split_suffixes(name: str) -> tuple[str, str]:
    """Split a filename into (base, extension) honouring compound extensions
    ('.tar.gz') so we don't chop 'backup.tar.gz' into ('backup.tar', '.gz')."""
    lowered = name.lower()
    for suf in _COMPOUND_SUFFIXES:
        if lowered.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)], name[-len(suf):]
    p = Path(name)
    return p.stem, p.suffix


def _nice_stem(name: str) -> str:
    """The user's original filename with its extension removed and reduced to a
    filesystem-/header-safe stem. Handles compound extensions so 'backup.tar.gz'
    yields 'backup' (not 'backup.tar')."""
    base, _ = _split_suffixes(Path(name).name)
    stem = _UNSAFE.sub("_", base).strip("._")
    return (stem or "output")[:80]


def _unique_target(target: Path) -> Path:
    """Return `target`, or `target` with a '-N' counter inserted before the
    extension if it already exists, so a nice-name collision never falls back to
    leaving the ugly uuid name in place."""
    if not target.exists():
        return target
    base, suf = _split_suffixes(target.name)
    i = 1
    while True:
        cand = target.with_name(f"{base}-{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def _rename_outputs(out_dir: Path, input_files: list[File]) -> None:
    """Rename outputs named after the internal uuid input stem back to the user's
    original filename stem, so downloads are friendly (e.g. invoice-compressed.pdf,
    backup.tar.gz, page.gz). Already-nice fixed names a tool chose itself
    (merged.pdf, qr.png, archive.zip, answer.txt) do not start with a uuid stem and
    are left untouched."""
    mapping: dict[str, str] = {}
    for f in input_files:
        # The stored name is "<uuid><suffix>"; strip *everything* after the first
        # dot so a compound stored suffix ('<uuid>.tar.gz') still yields the bare uuid.
        uuid_stem = Path(f.stored_path).name.split(".", 1)[0]
        nice = _nice_stem(f.orig_name)
        if uuid_stem and nice and uuid_stem != nice:
            mapping[uuid_stem] = nice
    if not mapping:
        return
    for p in [q for q in out_dir.rglob("*") if q.is_file()]:
        for uuid_stem, nice in mapping.items():
            if not p.name.startswith(uuid_stem):
                continue
            # Preserve everything the tool appended after the uuid: markers and
            # extensions alike ("-compressed.pdf", ".tar.gz", ".gz", "").
            target = p.with_name(nice + p.name[len(uuid_stem):])
            if target != p:
                try:
                    p.rename(_unique_target(target))
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


def run_tool(job_id: str, params: dict | None = None) -> None:
    """Execute one job: queued -> running -> done/error, wiping the workdir in finally.

    `params` carries the REAL parameters straight from the enqueue call so secrets
    (e.g. pdf passwords) never have to be read back from the DB, where they are stored
    redacted. When absent (older jobs / retries) we fall back to the redacted DB copy."""
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
            _publish_job(job)
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

            effective_params = dict(params) if params is not None else dict(job.params or {})
            ctx = ToolContext(
                job_id=jid,
                input_paths=input_paths,
                params=effective_params,
                workdir=workdir,
                output_dir=out_dir,
                progress_cb=lambda fraction, message="": _set_progress(jid, fraction, message),
            )
            tool.run(ctx)

            # Output-size guard: a small input can still produce a huge result
            # (uncapped gif/webm, OCR PDF/A bloat, media-download). Refuse to keep
            # or register a result set larger than the configured ceiling.
            max_output_bytes = settings.max_output_mb * 1024 * 1024
            total_output = 0
            for op in out_dir.rglob("*"):
                if op.is_file():
                    try:
                        total_output += op.stat().st_size
                    except OSError:
                        pass
            if total_output > max_output_bytes:
                shutil.rmtree(out_dir, ignore_errors=True)
                raise ToolError("output exceeds the size limit")

            _rename_outputs(out_dir, inputs)
            n_outputs = _register_outputs(db, job)
            job.status = "done"
            job.progress = 1.0
            job.finished_at = _utcnow()
            db.commit()
            _publish_job(job)
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


def run_batch(job_id: str, tool_slug: str, params: dict | None = None) -> None:
    """Run one single-file tool over every input file, zipping the per-file outputs."""
    jid = UUID(str(job_id))
    workdir = None
    try:
        with SessionLocal() as db:
            job = db.get(Job, jid)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = _utcnow()
            job.message = "starting batch"
            db.commit()
            _publish_job(job)

            tool = get_tool(tool_slug)
            if tool is None:
                raise ToolError(f"unknown tool '{tool_slug}'")
            inputs = (
                db.query(File).filter(File.job_id == jid, File.kind == "upload")
                .order_by(File.created_at).all()
            )
            if not inputs:
                raise ToolError("no input files")
            effective_params = dict(params) if params is not None else dict(job.params or {})

            workdir = tmp_dir(jid)
            workdir.mkdir(parents=True, exist_ok=True)
            out_dir = outputs_dir(jid)
            out_dir.mkdir(parents=True, exist_ok=True)

            total = len(inputs)
            n_ok = 0
            errors: list[str] = []
            zip_path = out_dir / f"batch-{tool.slug}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for i, f in enumerate(inputs):
                    path = file_abs_path(f.stored_path)
                    _set_progress(jid, i / total, f"{i + 1}/{total}: {f.orig_name}")
                    if not path.is_file():
                        errors.append(f"{f.orig_name}: file missing")
                        continue
                    sub_w = workdir / f"item{i}" / "work"
                    sub_o = workdir / f"item{i}" / "out"
                    sub_w.mkdir(parents=True, exist_ok=True)
                    sub_o.mkdir(parents=True, exist_ok=True)
                    ctx = ToolContext(jid, [path], dict(effective_params), sub_w, sub_o, progress_cb=None)
                    try:
                        tool.run(ctx)
                        # Map any "<uuid>*" output names back to the user's filename, just
                        # like single-file jobs, so no internal id leaks into the zip.
                        _rename_outputs(sub_o, [f])
                        nice = _nice_stem(f.orig_name)
                        for p in sorted(x for x in sub_o.rglob("*") if x.is_file()):
                            zf.write(p, arcname=f"{nice}/{p.relative_to(sub_o).as_posix()}")
                        n_ok += 1
                    except Exception as exc:  # noqa: BLE001 - collect per-file failure, keep going
                        errors.append(f"{f.orig_name}: {str(exc)[:120]}")
                    finally:
                        shutil.rmtree(workdir / f"item{i}", ignore_errors=True)

            if n_ok == 0:
                raise ToolError("all files failed — " + "; ".join(errors[:3]))
            max_output_bytes = settings.max_output_mb * 1024 * 1024
            if zip_path.stat().st_size > max_output_bytes:
                zip_path.unlink(missing_ok=True)
                raise ToolError("combined output exceeds the size limit")
            _register_outputs(db, job)
            job.status = "done"
            job.progress = 1.0
            job.finished_at = _utcnow()
            job.message = f"{n_ok}/{total} succeeded" + (f", {len(errors)} failed" if errors else "")
            db.commit()
            _publish_job(job)
            logger.info("batch job %s done (%d/%d ok)", jid, n_ok, total)
    except ToolError as exc:
        _mark_failed(jid, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("batch job %s crashed", jid)
        _mark_failed(jid, "internal error while running the batch")
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def run_pipeline(job_id: str, steps: list[dict] | None = None) -> None:
    """Run a linear chain of single-file tools: the output of each step becomes the
    input of the next. `steps` = [{"tool": slug, "params": {...}}, ...]."""
    jid = UUID(str(job_id))
    workdir = None
    try:
        with SessionLocal() as db:
            job = db.get(Job, jid)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = _utcnow()
            job.message = "starting pipeline"
            db.commit()
            _publish_job(job)

            chain = steps if steps is not None else (job.params or {}).get("steps") or []
            if not chain:
                raise ToolError("pipeline has no steps")
            inputs = (
                db.query(File).filter(File.job_id == jid, File.kind == "upload")
                .order_by(File.created_at).all()
            )
            input_paths = [file_abs_path(f.stored_path) for f in inputs]
            if len(input_paths) != 1:
                raise ToolError("a pipeline takes exactly one input file")
            if any(not p.is_file() for p in input_paths):
                raise ToolError("an input file is no longer available (it may have expired)")

            workdir = tmp_dir(jid)
            workdir.mkdir(parents=True, exist_ok=True)
            out_dir = outputs_dir(jid)
            out_dir.mkdir(parents=True, exist_ok=True)

            cur_paths = list(input_paths)
            stage_out: Path | None = None
            n = len(chain)
            for i, step in enumerate(chain):
                slug = step.get("tool")
                tool = get_tool(slug)
                if tool is None:
                    raise ToolError(f"unknown tool '{slug}' in step {i + 1}")
                if len(cur_paths) != 1:
                    raise ToolError(
                        f"step {i} produced {len(cur_paths)} files; each pipeline step takes one file"
                    )
                _set_progress(jid, i / n, f"step {i + 1}/{n}: {tool.name}")
                s_w = workdir / f"stage{i}" / "work"
                s_o = workdir / f"stage{i}" / "out"
                s_w.mkdir(parents=True, exist_ok=True)
                s_o.mkdir(parents=True, exist_ok=True)
                ctx = ToolContext(jid, list(cur_paths), dict(step.get("params") or {}), s_w, s_o, progress_cb=None)
                try:
                    tool.run(ctx)
                except ToolError as exc:
                    raise ToolError(f"step {i + 1} ({tool.name}): {exc}") from None
                except Exception:
                    logger.exception("pipeline step %d (%s) crashed", i + 1, tool.slug)
                    raise ToolError(
                        f"step {i + 1} ({tool.name}) failed — the input may be incompatible with this step"
                    ) from None
                outs = sorted(p for p in s_o.rglob("*") if p.is_file())
                if not outs:
                    raise ToolError(f"step {i + 1} ({tool.name}) produced no output")
                cur_paths = outs
                stage_out = s_o

            # Copy the last stage's outputs into the job output dir (preserving structure).
            assert stage_out is not None
            for p in cur_paths:
                dest = out_dir / p.relative_to(stage_out)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)

            max_output_bytes = settings.max_output_mb * 1024 * 1024
            total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
            if total > max_output_bytes:
                shutil.rmtree(out_dir, ignore_errors=True)
                raise ToolError("output exceeds the size limit")

            _rename_outputs(out_dir, inputs)
            n_outputs = _register_outputs(db, job)
            job.status = "done"
            job.progress = 1.0
            job.finished_at = _utcnow()
            job.message = f"{n} steps completed"
            db.commit()
            _publish_job(job)
            logger.info("pipeline job %s done (%d steps, %d output(s))", jid, n, n_outputs)
    except ToolError as exc:
        _mark_failed(jid, str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("pipeline job %s crashed", jid)
        _mark_failed(jid, "internal error while running the pipeline")
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    try:
        from .kb.schema import ensure_schema as kb_ensure_schema

        kb_ensure_schema()
    except Exception:
        logger.exception("kb schema setup failed in worker")
    ensure_dirs()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in ("default", "heavy")]
    logger.info("SelfX worker starting, consuming queues: default, heavy")
    Worker(queues, connection=connection).work()


if __name__ == "__main__":
    main()
