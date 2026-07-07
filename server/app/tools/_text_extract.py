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
        text = _from_pdf(path, max_chars)
    elif ext == ".docx":
        text = _from_docx(path)
    elif ext in (".txt", ".md", ".markdown"):
        text = _read_text_file(path)
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


def _read_text_file(path: Path) -> str:
    """Read a plain-text/markdown file, detecting its charset instead of mangling it.

    Uses charset-normalizer when available; otherwise falls back to explicit BOM
    handling then utf-8 -> latin-1 (latin-1 maps every byte, so it never raises).
    """
    raw = path.read_bytes()
    if not raw:
        return ""
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    # BOM-aware fallbacks
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")  # 1:1 byte mapping, cannot raise


def _from_pdf(path: Path, max_chars: int = MAX_CHARS) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        raise ToolError("the PDF reader is not available on this server") from None
    try:
        reader = PdfReader(str(path))
        pages = reader.pages
    except Exception:
        raise ToolError("could not read the PDF (it may be encrypted or corrupt)") from None

    parts: list[str] = []
    total = 0
    for page in pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            continue  # skip a single malformed page rather than failing the whole job
        if page_text:
            parts.append(page_text)
            total += len(page_text) + 1  # +1 for the join newline
            if total >= max_chars:
                break  # enough text — stop before parsing thousands of unused pages
    return "\n".join(parts)


def _from_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except Exception:
        raise ToolError("the Word reader is not available on this server") from None
    try:
        document = docx.Document(str(path))
    except Exception:
        raise ToolError("could not read the Word document") from None

    parts: list[str] = []
    # Section headers/footers (best-effort; some docs link/hide these).
    try:
        for section in document.sections:
            for hf in (section.header, section.footer):
                for p in hf.paragraphs:
                    if p.text and p.text.strip():
                        parts.append(p.text)
    except Exception:
        pass
    # Body paragraphs (the original happy path).
    for p in document.paragraphs:
        if p.text and p.text.strip():
            parts.append(p.text)
    # Tables — table-centric .docx would otherwise extract to near-empty.
    try:
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                if cells:
                    parts.append("\t".join(cells))
    except Exception:
        pass
    return "\n".join(parts)
