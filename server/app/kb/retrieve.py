"""Hybrid retrieval: pgvector cosine top-k + Postgres full-text (tsvector) top-k,
merged with Reciprocal Rank Fusion. Runs in the API process (not the worker)."""

import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..tools._ollama import embed_batch
from .models import Chunk, Collection

_RRF_K = 60


def retrieve(db: Session, collection: Collection, query: str, k: int = 8) -> list[Chunk]:
    """Return the top-k most relevant chunks for `query` in `collection`."""
    cid = collection.id
    qvec = embed_batch([query], collection.embed_model or settings.kb_embed_model)[0]

    # dense: cosine distance via pgvector
    dense_ids = list(db.execute(
        select(Chunk.id)
        .where(Chunk.collection_id == cid)
        .order_by(Chunk.embedding.cosine_distance(qvec))
        .limit(k * 2)
    ).scalars())

    # lexical: full-text rank over the generated tsv column (not mapped on the ORM)
    lexical_ids = [
        row[0] for row in db.execute(
            text(
                "SELECT id FROM kb_chunks "
                "WHERE collection_id = :cid AND tsv @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(tsv, plainto_tsquery('english', :q)) DESC LIMIT :k"
            ),
            {"cid": str(cid), "q": query, "k": k * 2},
        ).fetchall()
    ]

    # Reciprocal Rank Fusion
    scores: dict[uuid.UUID, float] = {}
    for ranked in (dense_ids, lexical_ids):
        for rank, cid_ in enumerate(ranked):
            scores[cid_] = scores.get(cid_, 0.0) + 1.0 / (_RRF_K + rank + 1)
    top = sorted(scores, key=lambda i: scores[i], reverse=True)[:k]
    if not top:
        return []

    by_id = {c.id: c for c in db.execute(select(Chunk).where(Chunk.id.in_(top))).scalars()}
    return [by_id[i] for i in top if i in by_id]
