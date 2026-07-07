"""doc-qa: answer a question about an uploaded document with a local LLM (SPEC §8).

Single-document Q&A that stuffs the (capped) document into the prompt — no vector
store needed for one document that fits the context window (REPORT §5, Phase A).
"""

from . import _ollama
from ._text_extract import extract_text
from .base import Tool, ToolContext
from .registry import register


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
        note = "\n\n[Note: the document was truncated to fit.]" if truncated else ""
        out_path = ctx.output_dir / "answer.txt"
        out_path.write_text(f"Q: {question}\n\nA: {answer}{note}\n", encoding="utf-8")
        ctx.progress(1.0, "done")
