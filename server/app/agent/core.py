"""Agent core: tool-spec conversion, the validated dispatch (via services.jobs), the
two instant in-process functions (kb_search / find_files), and job polling.

Both the Ollama and Gemini loops call `dispatch()`; neither can bypass the job gates.
"""

import copy
import time
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..kb import retrieve as kb_retrieve
from ..kb.models import Collection
from ..models import File, Job, User, utcnow
from ..services.jobs import create_and_run_job
from ..tools.registry import get_tool

# Curated subset exposed to the model — crisp, unambiguous tools route better than all 48.
EXPOSED_SLUGS = [
    "pdf-merge", "pdf-split", "pdf-compress", "pdf-rotate", "pdf-watermark",
    "pdf-protect", "pdf-unlock", "pdf-to-docx", "pdf-extract-text",
    "office-convert", "pandoc-convert", "html-to-pdf", "ocr-pdf",
    "image-convert", "image-remove-bg", "image-optimize", "image-caption",
    "media-convert", "audio-extract", "transcribe", "ai-summarize", "doc-qa",
    "metadata-remove", "archive-compress", "qr-generate", "barcode-generate",
    "hash-checksum", "virus-scan", "subtitle-convert", "gif-from-video", "video-trim",
]

INSTANT = {
    "kb_search": {
        "description": "Search a knowledge-base collection and return the most relevant passages. "
                       "Use to answer questions about the user's documents.",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "collection name"},
                "query": {"type": "string", "description": "what to look for"},
            },
            "required": ["collection", "query"],
        },
    },
    "find_files": {
        "description": "List the user's recently uploaded files (id, name, type) so you can pick one to process.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_POLL_TIMEOUT = 900


def fn_name(slug: str) -> str:
    return slug.replace("-", "_")


def slug_of(name: str) -> str:
    return name.replace("_", "-")


def build_specs() -> list[dict]:
    """One spec list feeds both Ollama and Gemini: {name, slug, kind, description, parameters}."""
    specs: list[dict] = []
    for slug in EXPOSED_SLUGS:
        tool = get_tool(slug)
        if tool is None:
            continue
        params = copy.deepcopy(tool.params_schema) or {"type": "object", "properties": {}}
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        if tool.min_files > 0:
            params["properties"]["file_ids"] = {
                "type": "array", "items": {"type": "string"},
                "description": "ids of uploaded files to process (from the attached-files list)",
            }
        specs.append({"name": fn_name(slug), "slug": slug, "kind": "tool",
                      "description": tool.description, "parameters": params})
    for name, spec in INSTANT.items():
        specs.append({"name": name, "slug": name, "kind": "instant",
                      "description": spec["description"], "parameters": spec["parameters"]})
    return specs


def gemini_safe_schema(s: dict | None) -> dict:
    """Reduce our JSON-Schema to Gemini's stricter OpenAPI subset: keep type/description/
    properties/required/items and STRING enums only; numeric enums fold into the
    description (the backend still enforces the real schema). Drops title/default/format/
    min*/max*/pattern/additionalProperties which Gemini rejects or ignores."""
    if not isinstance(s, dict):
        return {"type": "string"}
    t = s.get("type", "object")
    out: dict = {"type": t}
    desc = s.get("description", "")
    if t == "object":
        props = s.get("properties") or {}
        out["properties"] = {k: gemini_safe_schema(v) for k, v in props.items()}
        req = [r for r in (s.get("required") or []) if r in props]
        if req:
            out["required"] = req
    elif t == "array":
        out["items"] = gemini_safe_schema(s.get("items") or {"type": "string"})
    elif t == "string":
        enum = s.get("enum")
        if enum and all(isinstance(e, str) for e in enum):
            out["enum"] = enum
    elif t in ("integer", "number"):
        enum = s.get("enum")
        if enum:
            desc = (desc + f" (allowed: {', '.join(str(e) for e in enum)})").strip()
    if desc:
        out["description"] = desc
    return out


def file_manifest(db: Session, user: User, file_ids: list[uuid.UUID]) -> list[dict]:
    if not file_ids:
        return []
    rows = db.execute(select(File).where(File.id.in_(file_ids), File.user_id == user.id)).scalars()
    return [{"id": str(f.id), "name": f.orig_name, "type": f.mime} for f in rows]


# ---- instant functions ----
def _kb_search(args: dict, db: Session, user: User) -> dict:
    name = str(args.get("collection", "")).strip()
    query = str(args.get("query", "")).strip()
    col = db.execute(
        select(Collection).where(Collection.user_id == user.id, Collection.name.ilike(name))
    ).scalars().first()
    if col is None:
        cols = db.execute(select(Collection.name).where(Collection.user_id == user.id)).scalars().all()
        return {"ok": False, "error": f"no collection named '{name}'", "available_collections": list(cols)}
    passages = kb_retrieve.retrieve(db, col, query, k=6)
    return {"ok": True, "passages": [
        {"source": (p.meta or {}).get("source", "doc"), "text": p.text[:600]} for p in passages
    ]}


def _find_files(args: dict, db: Session, user: User) -> dict:
    rows = db.execute(
        select(File).where(File.user_id == user.id, File.kind == "upload", File.job_id.is_(None))
        .order_by(File.created_at.desc()).limit(20)
    ).scalars()
    return {"ok": True, "files": [{"id": str(f.id), "name": f.orig_name, "type": f.mime} for f in rows]}


def _poll_job(job_id: uuid.UUID) -> dict:
    end = time.monotonic() + _POLL_TIMEOUT
    while time.monotonic() < end:
        with SessionLocal() as s:
            job = s.get(Job, job_id)
            if job is None:
                return {"ok": False, "error": "job vanished"}
            if job.status in ("done", "error", "canceled"):
                outs = [{"id": str(f.id), "name": f.orig_name, "size": f.size}
                        for f in job.files if f.kind == "output"]
                return {"ok": job.status == "done", "status": job.status,
                        "outputs": outs, "error": job.error}
        time.sleep(1)
    return {"ok": False, "status": "timeout", "error": "the job took too long"}


def dispatch(name: str, args: dict, db: Session, user: User, attached_file_ids: list[uuid.UUID]) -> dict:
    """Run one model-chosen function. Returns a SMALL result dict (ids/names/status/snippets)."""
    args = dict(args or {})
    if name == "kb_search":
        return _kb_search(args, db, user)
    if name == "find_files":
        return _find_files(args, db, user)

    slug = slug_of(name)
    raw_ids = args.pop("file_ids", None)
    ids = raw_ids if raw_ids else [str(x) for x in attached_file_ids]
    try:
        file_ids = [uuid.UUID(str(x)) for x in (ids or [])]
    except ValueError:
        return {"ok": False, "error": "invalid file id"}
    try:
        job = create_and_run_job(db, user, slug, file_ids, args)
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not start the job: {exc}"}
    return _poll_job(job.id)
