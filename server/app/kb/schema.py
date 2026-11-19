"""PostgreSQL search structures that supplement the KB ORM tables."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_search_indexes(conn: Connection) -> None:
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
