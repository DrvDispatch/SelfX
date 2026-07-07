"""pdf-watermark: stamp diagonal text across every page of a PDF."""

import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas

from .base import Tool, ToolContext, ToolError
from .registry import register


def _overlay(width: float, height: float, text: str) -> "PdfReader":
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(45)
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.30))
    c.setFont("Helvetica-Bold", max(24, int(min(width, height) / 12)))
    c.drawCentredString(0, 0, text)
    c.restoreState()
    c.save()
    buf.seek(0)
    return PdfReader(buf)


@register
class PdfWatermark(Tool):
    slug = "pdf-watermark"
    name = "Watermark PDF"
    category = "pdf"
    description = "Stamp semi-transparent diagonal text (e.g. CONFIDENTIAL) across every page."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "title": "Watermark text",
                "minLength": 1,
                "maxLength": 60,
                "default": "CONFIDENTIAL",
            }
        },
        "required": ["text"],
    }

    def run(self, ctx: ToolContext) -> None:
        text = str(ctx.params.get("text", "CONFIDENTIAL"))
        src = ctx.input_paths[0]
        try:
            reader = PdfReader(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file") from None
        if reader.is_encrypted:
            raise ToolError("the PDF is password-protected — unlock it first")

        writer = PdfWriter()
        total = len(reader.pages) or 1
        for i, page in enumerate(reader.pages):
            ctx.progress(i / total, f"watermarking page {i + 1}")
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            overlay = _overlay(w, h, text).pages[0]
            page.merge_page(overlay)
            writer.add_page(page)
        with (ctx.output_dir / f"{src.stem}-watermarked.pdf").open("wb") as fh:
            writer.write(fh)
        ctx.progress(1.0, "done")
