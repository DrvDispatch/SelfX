"""Shared helpers for the document tools (office/html/pandoc/ebook/ocr).

Small, dependency-light utilities used to validate SEMANTIC output (a PDF that
actually has pages) rather than trusting ``st_size > 0``.
"""

from pathlib import Path

from .base import ToolError


def pdf_page_count(path: Path) -> int:
    """Return the page count of a PDF, or -1 if it cannot be parsed as a PDF.

    Best-effort: uses pypdf (a declared dependency). Never raises.
    """
    try:
        from pypdf import PdfReader
    except Exception:
        return -1
    try:
        reader = PdfReader(str(path))
        # get_num_pages avoids fully loading every page object where possible.
        return len(reader.pages)
    except Exception:
        return -1


def validate_pdf_output(path: Path, min_pages: int = 1) -> None:
    """Raise ToolError unless ``path`` is a non-empty PDF with >= min_pages pages.

    Falls back to a header + size check when pypdf cannot parse the file, so a
    genuinely-valid-but-unusual PDF is not rejected on a parser quirk.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise ToolError("conversion produced no output — the file may be unsupported or corrupt")
    pages = pdf_page_count(path)
    if pages == 0:
        raise ToolError("conversion produced an empty (0-page) PDF — the input may be blank or corrupt")
    if pages < 0:
        # pypdf could not parse it; accept only if it at least looks like a PDF.
        try:
            head = path.read_bytes()[:5]
        except Exception:
            head = b""
        if not head.startswith(b"%PDF"):
            raise ToolError("conversion produced an invalid PDF — the input may be unsupported or corrupt")
        return
    if pages < min_pages:
        raise ToolError("conversion produced an empty PDF — the input may be blank or corrupt")
