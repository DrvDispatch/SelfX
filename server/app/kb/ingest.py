"""KB ingestion job (runs in the RQ worker): parse a document -> chunk -> embed
(local Ollama, batched) -> upsert Chunk rows. Enqueued by the KB API.
"""

import logging
from uuid import UUID

from ..config import settings
from ..db import SessionLocal
from ..models import File
from ..storage import file_abs_path
from ..tools._ollama import embed_batch
from ..tools._text_extract import extract_text
from ..tools.multi_doc_qa import _chunk
from .models import Chunk, Document

logger = logging.getLogger("selfx.kb.ingest")


def ingest_document(document_id: str) -> None:
    doc_id = UUID(str(document_id))
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.error("kb ingest: document %s not found", doc_id)
            return
        doc.status = "indexing"
        db.commit()
        try:
            src = db.get(File, doc.source_file_id) if doc.source_file_id else None
            if src is None:
                raise RuntimeError("source file is missing")
            path = file_abs_path(src.stored_path)
            if not path.is_file():
                raise RuntimeError("source file is no longer on disk")

            text, _ = extract_text(path, max_chars=2_000_000)
            chunks = [c for c in _chunk(text) if c.strip()]
            if not chunks:
                raise RuntimeError("no text could be extracted from this document")

            embed_model = doc.collection.embed_model or settings.kb_embed_model
            vectors = embed_batch(chunks, embed_model)
            if len(vectors) != len(chunks):
                raise RuntimeError("embedding count mismatch")

            # re-ingest is idempotent: drop this document's old chunks first
            db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
            for i, (chunk_text, vec) in enumerate(zip(chunks, vectors)):
                db.add(Chunk(
                    document_id=doc.id,
                    collection_id=doc.collection_id,
                    ordinal=i,
                    text=chunk_text,
                    meta={"source": doc.orig_name},
                    embedding=vec,
                ))
            doc.status = "indexed"
            doc.n_chunks = len(chunks)
            doc.error = None
            db.commit()
            logger.info("kb ingest: document %s indexed (%d chunks)", doc_id, len(chunks))
        except Exception as exc:  # noqa: BLE001 - record any failure on the document row
            db.rollback()
            doc = db.get(Document, doc_id)
            if doc is not None:
                doc.status = "error"
                doc.error = str(exc)[:500]
                db.commit()
            logger.exception("kb ingest failed for document %s", doc_id)
