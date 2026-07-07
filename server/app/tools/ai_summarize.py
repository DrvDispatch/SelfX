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

# Map-reduce sizing: chunks small enough to fit the context window comfortably, and
# a cap on how many chunks we summarize so a huge doc can't blow the job budget.
_CHUNK_CHARS = 10_000
_MAX_MAP_CHUNKS = 12
_EXTRACT_CHARS = _CHUNK_CHARS * _MAX_MAP_CHUNKS  # 120k chars ~ 60-80 pages


def _split(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


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
        lang_note = "" if language == "auto" else f" Respond in {language}."
        system = "You are a precise summarizer." + lang_note

        ctx.progress(0.2, "extracting text")
        text, truncated = extract_text(ctx.input_paths[0], max_chars=_EXTRACT_CHARS)
        chunks = _split(text)

        if len(chunks) <= 1:
            ctx.progress(0.5, "summarizing with local AI")
            content = _ollama.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"{instruction}\n\nDocument:\n{text}"},
                ]
            )
        else:
            # Map: summarize each chunk faithfully. Reduce: combine the partials.
            partials = []
            for i, chunk in enumerate(chunks):
                ctx.progress(0.3 + 0.5 * (i / len(chunks)), f"summarizing part {i + 1}/{len(chunks)}")
                part = _ollama.chat(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content":
                            f"This is part {i + 1} of {len(chunks)} of a longer document. "
                            f"Summarize the key points of THIS part faithfully.\n\n{chunk}"},
                    ]
                )
                partials.append(part)
            ctx.progress(0.85, "combining section summaries")
            combined = "\n\n".join(f"[Part {i + 1}]\n{p}" for i, p in enumerate(partials))
            content = _ollama.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content":
                        f"{instruction}\n\nThe text below is a set of section summaries of ONE "
                        f"document. Write a single unified summary of the whole document; do not "
                        f"refer to 'parts' or 'sections'.\n\n{combined}"},
                ]
            )

        note = "\n\n[Note: the document was long and only its first portion was summarized.]" if truncated else ""
        out_path = ctx.output_dir / f"{ctx.input_paths[0].stem}-summary.txt"
        out_path.write_text(content + note, encoding="utf-8")
        ctx.progress(1.0, "done")
