"""Knowledge base API: collections, document ingestion, and grounded chat (RAG)."""

import hashlib
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..kb import answer as kb_answer
from ..kb import retrieve as kb_retrieve
from ..kb.models import Chunk, Collection, Document, KbMessage
from ..models import File, User
from ..queueing import enqueue_kb_ingest
from ..storage import file_abs_path
from ..tools import _ollama

logger = logging.getLogger("selfx.routes.kb")
router = APIRouter(prefix="/kb", tags=["knowledge-base"])


# ---- schemas ----
class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CollectionOut(BaseModel):
    id: UUID
    name: str
    embed_model: str
    allow_cloud: bool
    documents: int
    chunks: int


class DocumentOut(BaseModel):
    id: UUID
    orig_name: str
    status: str
    n_chunks: int
    error: str | None


class IngestRequest(BaseModel):
    file_ids: list[UUID] = Field(min_length=1)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)


# ---- helpers ----
def _own_collection(cid: UUID, user: User, db: Session) -> Collection:
    col = db.get(Collection, cid)
    if col is None or (col.user_id != user.id and not user.is_admin):
        raise HTTPException(status_code=404, detail="collection not found")
    return col


def _collection_out(db: Session, col: Collection) -> CollectionOut:
    docs = db.scalar(select(func.count()).select_from(Document).where(Document.collection_id == col.id)) or 0
    chunks = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.collection_id == col.id)) or 0
    return CollectionOut(id=col.id, name=col.name, embed_model=col.embed_model,
                         allow_cloud=col.allow_cloud, documents=docs, chunks=chunks)


# ---- collections ----
@router.get("/collections", response_model=list[CollectionOut])
def list_collections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cols = db.scalars(select(Collection).where(Collection.user_id == user.id).order_by(Collection.created_at)).all()
    return [_collection_out(db, c) for c in cols]


@router.post("/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = Collection(user_id=user.id, name=payload.name.strip())
    db.add(col)
    db.commit()
    db.refresh(col)
    return _collection_out(db, col)


@router.delete("/collections/{cid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(cid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = _own_collection(cid, user, db)
    db.delete(col)  # cascade removes documents + chunks + messages
    db.commit()


# ---- documents / ingestion ----
@router.get("/collections/{cid}/documents", response_model=list[DocumentOut])
def list_documents(cid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_collection(cid, user, db)
    docs = db.scalars(select(Document).where(Document.collection_id == cid).order_by(Document.created_at)).all()
    return [DocumentOut(id=d.id, orig_name=d.orig_name, status=d.status, n_chunks=d.n_chunks, error=d.error) for d in docs]


@router.post("/collections/{cid}/documents", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED)
def add_documents(cid: UUID, payload: IngestRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = _own_collection(cid, user, db)
    ok, reason = _ollama.is_available()
    if not ok or not _ollama.has_model(col.embed_model):
        raise HTTPException(status_code=409, detail=f"the embedding model '{col.embed_model}' is not available in Ollama")

    out: list[DocumentOut] = []
    for fid in payload.file_ids:
        f = db.get(File, fid)
        if f is None or (f.user_id != user.id and not user.is_admin) or f.kind != "upload":
            raise HTTPException(status_code=404, detail=f"file {fid} not found")
        path = file_abs_path(f.stored_path)
        content_hash = None
        if path.is_file():
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            content_hash = h.hexdigest()
        f.expires_at = None  # KB source files are exempt from retention
        doc = Document(collection_id=col.id, user_id=user.id, orig_name=f.orig_name,
                       source_file_id=f.id, content_hash=content_hash, status="pending")
        db.add(doc)
        db.flush()
        enqueue_kb_ingest(doc.id)
        out.append(DocumentOut(id=doc.id, orig_name=doc.orig_name, status=doc.status, n_chunks=0, error=None))
    db.commit()
    return out


# ---- chat ----
class ChatResponse(BaseModel):
    answer: str
    citations: list[dict]
    sources: list[str]


@router.post("/collections/{cid}/chat", response_model=ChatResponse)
def chat(cid: UUID, payload: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = _own_collection(cid, user, db)
    ok, reason = _ollama.is_available()
    if not ok:
        raise HTTPException(status_code=409, detail=reason or "the local AI service is not running")

    passages = kb_retrieve.retrieve(db, col, payload.question, k=payload.top_k)
    reply, citations = kb_answer.answer(col, payload.question, passages)
    sources = sorted({c["document"] for c in citations})

    db.add(KbMessage(collection_id=col.id, user_id=user.id, role="user", content=payload.question))
    db.add(KbMessage(collection_id=col.id, user_id=user.id, role="assistant", content=reply, citations={"items": citations}))
    db.commit()
    return ChatResponse(answer=reply, citations=citations, sources=sources)


@router.get("/collections/{cid}/messages")
def messages(cid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_collection(cid, user, db)
    msgs = db.scalars(select(KbMessage).where(KbMessage.collection_id == cid).order_by(KbMessage.created_at)).all()
    return [{"role": m.role, "content": m.content, "citations": (m.citations or {}).get("items", [])} for m in msgs]
