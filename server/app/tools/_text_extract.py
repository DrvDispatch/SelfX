"""Shared text extraction for the AI tools (leading underscore => not a tool module).

Pulls plain text out of PDF / DOCX / TXT / MD for summarization and Q&A, capped so
we never blow the LLM context window.
"""

from pathlib import Path

from .base import ToolError

MAX_CHARS = 24_000


def extract_text(path: Path, max_chars: int = MAX_CHARS) -> tuple[str, bool]:
    """Return (text, truncated). Raises ToolError for unsupported/empty inputs."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        text = _from_pdf(path)
    elif ext == ".docx":
        text = _from_docx(path)
    elif ext in (".txt", ".md", ".markdown"):
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        raise ToolError(f"unsupported document type '{ext}'")

    text = text.strip()
    if not text:
        raise ToolError(
            "no text could be extracted — the document may be empty or a scanned image "
            "(run OCR first)"
        )
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def _from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        raise ToolError("the PDF reader is not available on this server") from None
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        raise ToolError("could not read the PDF (it may be encrypted or corrupt)") from None


def _from_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except Exception:
        raise ToolError("the Word reader is not available on this server") from None
    try:
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)
    except Exception:
        raise ToolError("could not read the Word document") from None
