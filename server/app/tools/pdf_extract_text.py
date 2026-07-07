"""pdf-extract-text: pull the text layer out of a PDF into a .txt file."""

from pypdf import PdfReader

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfExtractText(Tool):
    slug = "pdf-extract-text"
    name = "Extract text from PDF"
    category = "pdf"
    description = "Extract the text layer of a PDF to a plain-text file (scanned PDFs need OCR first)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        try:
            reader = PdfReader(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file") from None
        if reader.is_encrypted:
            raise ToolError("the PDF is password-protected — unlock it first")

        parts = []
        total = len(reader.pages) or 1
        for i, page in enumerate(reader.pages):
            ctx.progress(i / total, f"reading page {i + 1}")
            # One malformed page must not abort the whole document — skip it.
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        text = "\n\n".join(parts).strip()
        if not text:
            raise ToolError("no text found — this PDF may be scanned; run OCR first")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, "done")
