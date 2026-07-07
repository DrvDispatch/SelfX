"""pdf-watermark: stamp diagonal text across every page of a PDF."""

import io
import os

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .base import Tool, ToolContext, ToolError
from .registry import register

_FONT_NAME: str | None = None


def _watermark_font() -> str:
    """Register a bundled Unicode TTF once so CJK/RTL/accented text renders instead of
    tofu (or an encoding error). Falls back to reportlab's built-in Helvetica-Bold."""
    global _FONT_NAME
    if _FONT_NAME is not None:
        return _FONT_NAME
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    # Bitstream Vera ships INSIDE reportlab (always installed here) — covers
    # Latin/Cyrillic/Greek, so it is a reliable "bundled Unicode TTF".
    try:
        import reportlab

        rdir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
        candidates += [os.path.join(rdir, "VeraBd.ttf"), os.path.join(rdir, "Vera.ttf")]
    except Exception:
        pass
    candidates += ["C:/Windows/Fonts/arialuni.ttf", "C:/Windows/Fonts/arial.ttf"]
    for path in candidates:
        try:
            if os.path.isfile(path):
                pdfmetrics.registerFont(TTFont("SelfXWatermark", path))
                _FONT_NAME = "SelfXWatermark"
                return _FONT_NAME
        except Exception:
            continue
    _FONT_NAME = "Helvetica-Bold"
    return _FONT_NAME


def _overlay(
    width: float, height: float, text: str, font_name: str, extra_rotate: float = 0.0
) -> "PdfReader":
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.saveState()
    c.translate(width / 2, height / 2)
    # reportlab rotates counter-clockwise; a page's /Rotate is applied clockwise on
    # display, so add it back to keep the stamp diagonal in the viewed orientation.
    c.rotate(45 + extra_rotate)
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.30))
    c.setFont(font_name, max(24, int(min(width, height) / 12)))
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
        font_name = _watermark_font()
        pages = reader.pages
        total = len(pages) or 1
        kept = 0
        for i, page in enumerate(pages):
            ctx.progress(i / total, f"watermarking page {i + 1}")
            # A single malformed page must not abort the whole document: on failure,
            # keep the page (unstamped) and carry on.
            try:
                w = float(page.mediabox.width)
                h = float(page.mediabox.height)
                try:
                    rotate = int(page.rotation or 0) % 360
                except Exception:
                    rotate = 0
                overlay = _overlay(w, h, text, font_name, extra_rotate=rotate).pages[0]
                page.merge_page(overlay)
            except Exception:
                pass
            writer.add_page(page)
            kept += 1
        if kept == 0:
            raise ToolError("the PDF has no pages to watermark")
        with (ctx.output_dir / f"{src.stem}-watermarked.pdf").open("wb") as fh:
            writer.write(fh)
        ctx.progress(1.0, "done")
