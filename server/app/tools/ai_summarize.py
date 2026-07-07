"""ai-summarize: summarize a document with a local LLM via Ollama (SPEC §8)."""

from . import _ollama
from ._text_extract import extract_text
from .base import Tool, ToolContext
from .registry import register

_LENGTH = {
    "short": "Write a concise 2-3 sentence summary.",
    "medium": "Write a summary of about one paragraph.",
    "detailed": "Write a thorough summary with the key points as a bulleted list.",
}


@register
class AiSummarize(Tool):
    slug = "ai-summarize"
    name = "AI Summarize"
    category = "ai"
    description = "Summarize a PDF, Word, text or Markdown document with a local LLM."
    accepts = [".pdf", ".txt", ".md", ".markdown", ".docx"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "length": {
                "type": "string",
                "title": "Length",
                "enum": ["short", "medium", "detailed"],
                "default": "medium",
            },
            "language": {
                "type": "string",
                "title": "Output language",
                "enum": ["auto", "english", "german", "french", "spanish", "arabic", "chinese"],
                "default": "auto",
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        return _ollama.is_available()

    def run(self, ctx: ToolContext) -> None:
        length = str(ctx.params.get("length", "medium"))
        language = str(ctx.params.get("language", "auto"))
        instruction = _LENGTH.get(length, _LENGTH["medium"])

        ctx.progress(0.2, "extracting text")
        text, truncated = extract_text(ctx.input_paths[0])
        lang_note = "" if language == "auto" else f" Respond in {language}."
        note = "\n\n[Note: the document was truncated to fit.]" if truncated else ""

        ctx.progress(0.5, "summarizing with local AI")
        content = _ollama.chat(
            [
                {"role": "system", "content": "You are a precise summarizer." + lang_note},
                {"role": "user", "content": f"{instruction}\n\nDocument:\n{text}"},
            ]
        )
        out_path = ctx.output_dir / f"{ctx.input_paths[0].stem}-summary.txt"
        out_path.write_text(content + note, encoding="utf-8")
        ctx.progress(1.0, "done")
