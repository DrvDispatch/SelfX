"""multi-doc-qa: retrieval-augmented Q&A across several documents (RAG).

Chunks the uploaded documents, embeds them with a local embedding model (Ollama
nomic-embed-text), retrieves the most relevant passages for the question, and asks
the local LLM to answer from those passages. Ephemeral — nothing is stored.
"""

from . import _ollama
from ._text_extract import extract_text
from .base import Tool, ToolContext, ToolError
from .registry import register

_EMBED_MODEL = "nomic-embed-text"
_MAX_CHUNKS = 200  # safety cap on how much we embed per job


def _chunk(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + size].strip()
        if piece:
            out.append(piece)
        i += size - overlap
    return out


@register
class MultiDocQa(Tool):
    slug = "multi-doc-qa"
    name = "Chat with documents (RAG)"
    category = "ai"
    description = "Ask a question across one or more documents; the answer is grounded in the most relevant passages."
    accepts = [".pdf", ".txt", ".md", ".markdown", ".docx"]
    multi_file = True
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "title": "Question",
                "minLength": 1,
                "maxLength": 1000,
            },
            "top_k": {
                "type": "integer",
                "title": "Passages to use",
                "minimum": 1,
                "maximum": 20,
                "default": 6,
            },
            "chunk_size": {
                "type": "integer",
                "title": "Chunk size (characters)",
                "description": "How large each indexed passage is.",
                "minimum": 200,
                "maximum": 8000,
                "default": 1500,
            },
            "chunk_overlap": {
                "type": "integer",
                "title": "Chunk overlap (characters)",
                "description": "Characters shared between neighbouring chunks so answers spanning a boundary aren't lost.",
                "minimum": 0,
                "maximum": 2000,
                "default": 200,
            },
            "min_score": {
                "type": "number",
                "title": "Minimum similarity",
                "description": "Drop retrieved passages below this cosine score (0 disables filtering).",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.0,
            },
            "max_chunks": {
                "type": "integer",
                "title": "Max passages to index",
                "description": "Safety cap on how many passages are embedded per job.",
                "minimum": 10,
                "maximum": 2000,
                "default": 200,
            },
        },
        "required": ["question"],
    }

    def available(self) -> tuple[bool, str | None]:
        ok, reason = _ollama.is_available()
        if not ok:
            return ok, reason
        if not _ollama.has_model(_EMBED_MODEL):
            return False, f"the embedding model '{_EMBED_MODEL}' is not pulled in Ollama"
        return True, None

    def run(self, ctx: ToolContext) -> None:
        import numpy as np

        question = str(ctx.params["question"]).strip()
        top_k = int(ctx.params.get("top_k", 6))

        # Opt-in retrieval controls — clamped so bad input can't break the job.
        def _clamp_int(key, default, lo, hi):
            try:
                v = int(ctx.params.get(key, default))
            except (TypeError, ValueError):
                v = default
            return max(lo, min(v, hi))

        chunk_size = _clamp_int("chunk_size", 1500, 200, 8000)
        chunk_overlap = _clamp_int("chunk_overlap", 200, 0, 2000)
        # Guarantee forward progress in _chunk (step = size - overlap must be > 0).
        if chunk_overlap >= chunk_size:
            chunk_overlap = chunk_size - 1
        max_chunks = _clamp_int("max_chunks", _MAX_CHUNKS, 10, 2000)
        try:
            min_score = float(ctx.params.get("min_score", 0.0))
        except (TypeError, ValueError):
            min_score = 0.0
        min_score = max(0.0, min(min_score, 1.0))

        ctx.progress(0.1, "extracting text")
        # Collect chunks per document so the global cap can be shared fairly across
        # files instead of being filled by the first documents (ordering bias).
        per_doc: list[tuple[str, list[str]]] = []
        for path in ctx.input_paths:
            text, _ = extract_text(path, max_chars=200_000)
            chunks = _chunk(text, size=chunk_size, overlap=chunk_overlap)
            if chunks:
                per_doc.append((path.stem, chunks))
        if not per_doc:
            raise ToolError("no text could be extracted from the documents")

        # Round-robin across documents so later files are not dropped entirely.
        passages: list[tuple[str, str]] = []
        depth = 0
        while len(passages) < max_chunks:
            added = False
            for name, chunks in per_doc:
                if depth < len(chunks):
                    added = True
                    passages.append((name, chunks[depth]))
                    if len(passages) >= max_chunks:
                        break
            if not added:
                break
            depth += 1

        total_chunks = sum(len(c) for _, c in per_doc)
        truncated = total_chunks > len(passages)

        ctx.progress(0.4, f"embedding {len(passages)} passages")
        # nomic-embed-text expects task prefixes for best retrieval quality. Embed the
        # query in the SAME batch as the passages so both use the identical endpoint.
        texts = [f"search_document: {ch}" for _, ch in passages]
        texts.append(f"search_query: {question}")
        all_vecs = _ollama.embed_batch(texts, _EMBED_MODEL)
        doc_vecs = all_vecs[:-1]
        qv = np.asarray(all_vecs[-1], dtype="float32")

        ctx.progress(0.75, "retrieving relevant passages")
        mat = np.asarray(doc_vecs, dtype="float32")
        mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
        qn = qv / (np.linalg.norm(qv) + 1e-8)
        sims = mat_n @ qn
        order = sims.argsort()[::-1]
        top = order[:top_k]
        if min_score > 0.0:
            # Drop weak matches, but always keep at least the single best passage so
            # the model still has something to ground on.
            kept = [int(i) for i in top if float(sims[int(i)]) >= min_score]
            top = kept if kept else [int(order[0])]
        context = "\n\n".join(f"[{passages[i][0]}]\n{passages[i][1]}" for i in top)

        ctx.progress(0.85, "answering from the retrieved passages")
        answer = _ollama.chat([
            {"role": "system", "content": "Answer the question using ONLY the provided passages. "
                                          "Cite the source names in [brackets]. If the passages do "
                                          "not contain the answer, say so."},
            {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
        ])
        note = ""
        if truncated:
            indexed = len({name for name, _ in passages})
            note = (
                f"\n\n[Note: {len(passages)} of {total_chunks} passages across {indexed} "
                f"document(s) were indexed; some content was not searched.]"
            )
        (ctx.output_dir / "answer.txt").write_text(
            f"Q: {question}\n\nA: {answer}{note}\n", encoding="utf-8"
        )
        ctx.progress(1.0, "done")
