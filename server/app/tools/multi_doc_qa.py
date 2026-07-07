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

        ctx.progress(0.1, "extracting text")
        # Collect chunks per document so the global cap can be shared fairly across
        # files instead of being filled by the first documents (ordering bias).
        per_doc: list[tuple[str, list[str]]] = []
        for path in ctx.input_paths:
            text, _ = extract_text(path, max_chars=200_000)
            chunks = _chunk(text)
            if chunks:
                per_doc.append((path.stem, chunks))
        if not per_doc:
            raise ToolError("no text could be extracted from the documents")

        # Round-robin across documents so later files are not dropped entirely.
        passages: list[tuple[str, str]] = []
        depth = 0
        while len(passages) < _MAX_CHUNKS:
            added = False
            for name, chunks in per_doc:
                if depth < len(chunks):
                    added = True
                    passages.append((name, chunks[depth]))
                    if len(passages) >= _MAX_CHUNKS:
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
        top = sims.argsort()[::-1][:top_k]
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
