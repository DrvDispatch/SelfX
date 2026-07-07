"""Grounded answer synthesis over retrieved chunks, with citations.

Defaults to LOCAL Ollama. A collection may opt into cloud (Gemini) synthesis via
`allow_cloud`; that path is wired when the agent's Gemini client lands (kept local
until then so nothing leaves the box by default)."""

from .models import Chunk, Collection

_SYSTEM = (
    "You answer questions using ONLY the numbered passages provided. Cite the "
    "passages you use inline as [1], [2], etc. If the passages do not contain the "
    "answer, say so plainly — do not invent facts."
)


def _citations(passages: list[Chunk]) -> list[dict]:
    out = []
    for i, p in enumerate(passages, 1):
        out.append({
            "n": i,
            "document": (p.meta or {}).get("source", "document"),
            "ordinal": p.ordinal,
            "snippet": (p.text or "")[:240],
        })
    return out


def answer(collection: Collection, question: str, passages: list[Chunk]) -> tuple[str, list[dict]]:
    from ..tools import _ollama

    if not passages:
        return ("I couldn't find anything relevant in this collection for that question.", [])

    context = "\n\n".join(
        f"[{i}] (source: {(p.meta or {}).get('source', 'document')}, chunk {p.ordinal})\n{p.text}"
        for i, p in enumerate(passages, 1)
    )
    reply = _ollama.chat([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Passages:\n{context}\n\nQuestion: {question}"},
    ])
    return reply, _citations(passages)
