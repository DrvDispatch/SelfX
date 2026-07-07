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

        passages: list[tuple[str, str]] = []
        for path in ctx.input_paths:
            text, _ = extract_text(path, max_chars=200_000)
            for ch in _chunk(text):
                passages.append((path.stem, ch))
        if not passages:
            raise ToolError("no text could be extracted from the documents")
        truncated = len(passages) > _MAX_CHUNKS
        passages = passages[:_MAX_CHUNKS]

        vecs = []
        for i, (_, ch) in enumerate(passages):
            vecs.append(_ollama.embed(ch, _EMBED_MODEL))
            ctx.progress(0.1 + 0.6 * (i / len(passages)), f"indexing passage {i + 1}/{len(passages)}")
        mat = np.asarray(vecs, dtype="float32")
        qv = np.asarray(_ollama.embed(question, _EMBED_MODEL), dtype="float32")

        mat_n = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
        qn = qv / (np.linalg.norm(qv) + 1e-8)
        sims = mat_n @ qn
        top = sims.argsort()[::-1][:top_k]
        context = "\n\n".join(f"[{passages[i][0]}]\n{passages[i][1]}" for i in top)

        ctx.progress(0.8, "answering from the retrieved passages")
        answer = _ollama.chat([
            {"role": "system", "content": "Answer the question using ONLY the provided passages. "
                                          "Cite the source names in [brackets]. If the passages do "
                                          "not contain the answer, say so."},
            {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
        ])
        note = "\n\n[Note: only the first passages were indexed.]" if truncated else ""
        (ctx.output_dir / "answer.txt").write_text(
            f"Q: {question}\n\nA: {answer}{note}\n", encoding="utf-8"
        )
        ctx.progress(1.0, "done")
