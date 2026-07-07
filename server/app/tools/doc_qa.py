"""doc-qa: answer a question about an uploaded document with a local LLM (SPEC §8).

Single-document Q&A that stuffs the (capped) document into the prompt — no vector
store needed for one document that fits the context window (REPORT §5, Phase A).
"""

from . import _ollama
from ._text_extract import extract_text
from .base import Tool, ToolContext
from .registry import register

# Phrases a grounded model uses when the answer isn't in the provided text. Used only
# to decide whether to suggest the RAG tool — never to alter the model's answer.
_NOT_FOUND_HINTS = (
    "not in the document", "not contain", "does not contain", "doesn't contain",
    "cannot find", "can't find", "no information", "not mentioned", "not provided",
    "isn't in", "is not in", "not found", "no mention", "not stated", "not specified",
)


def _looks_not_found(answer: str) -> bool:
    low = answer.lower()
    return any(h in low for h in _NOT_FOUND_HINTS)


@register
class DocQa(Tool):
    slug = "doc-qa"
    name = "Ask a document"
    category = "ai"
    description = "Ask a question and get an answer grounded in your uploaded document (local LLM)."
    accepts = [".pdf", ".txt", ".md", ".markdown", ".docx"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "title": "Question",
                "description": "What do you want to know about the document?",
                "minLength": 1,
                "maxLength": 1000,
            }
        },
        "required": ["question"],
    }

    def available(self) -> tuple[bool, str | None]:
        return _ollama.is_available()

    def run(self, ctx: ToolContext) -> None:
        question = str(ctx.params["question"]).strip()
        ctx.progress(0.2, "extracting text")
        text, truncated = extract_text(ctx.input_paths[0])

        ctx.progress(0.5, "asking the local AI")
        answer = _ollama.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Answer the user's question using ONLY the provided document. "
                        "If the answer is not in the document, say so plainly."
                    ),
                },
                {"role": "user", "content": f"Document:\n{text}\n\nQuestion: {question}"},
            ]
        )
        notes = []
        if truncated:
            notes.append("only the first part of the document was searched")
        # When the answer wasn't found (or the doc was truncated), nudge toward RAG,
        # which searches the WHOLE document instead of only the stuffed prefix.
        if truncated or _looks_not_found(answer):
            notes.append(
                "if the answer may be elsewhere in the document, try the 'Chat with documents "
                "(RAG)' tool (multi-doc-qa), which searches the whole document"
            )
        note = ("\n\n[Note: " + "; ".join(notes) + ".]") if notes else ""
        out_path = ctx.output_dir / "answer.txt"
        out_path.write_text(f"Q: {question}\n\nA: {answer}{note}\n", encoding="utf-8")
        ctx.progress(1.0, "done")
