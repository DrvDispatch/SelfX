"""Idempotent knowledge-base schema setup: pgvector extension, tables, and the
generated tsvector column + HNSW/GIN indexes. Safe to call at every startup.

Runs from both the API lifespan and the worker init so either process can create
the schema. `init_db()` handles the base tables; this handles the vector bits.
"""

import logging

from sqlalchemy import text

from ..db import Base, engine

logger = logging.getLogger("selfx.kb")

_done = False


def ensure_schema() -> None:
    global _done
    if _done:
        return
    # 1) extension MUST exist before any Vector column is created
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 2) register + create kb tables (base app tables are a no-op if already present)
    from . import models  # noqa: F401  (register mappings on Base.metadata)

    Base.metadata.create_all(bind=engine)

    # 3) generated tsvector column for lexical search + the ANN / GIN indexes
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw "
            "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS kb_chunks_tsv_gin ON kb_chunks USING gin (tsv)"
        ))
    _done = True
    logger.info("knowledge-base schema ready (pgvector + hnsw + tsvector)")
