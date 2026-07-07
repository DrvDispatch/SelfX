"""pdf-to-images: render each PDF page to an image with PDFium (permissive)."""

import io
import zipfile

import pypdfium2 as pdfium
from PIL import Image

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfToImages(Tool):
    slug = "pdf-to-images"
    name = "PDF to images"
    category = "pdf"
    description = "Render each page of a PDF to a PNG or JPEG image (returned as a zip for multi-page)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "title": "Image format",
                "enum": ["png", "jpg"],
                "default": "png",
            },
            "dpi": {
                "type": "integer",
                "title": "Resolution (DPI)",
                "minimum": 36,
                "maximum": 600,
                "default": 150,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "png"))
        pil_fmt = "JPEG" if fmt == "jpg" else "PNG"
        dpi = int(ctx.params.get("dpi", 150))
        scale = dpi / 72.0
        src = ctx.input_paths[0]
        try:
            doc = pdfium.PdfDocument(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file (or is password-protected)") from None
        try:
            n = len(doc)
            if n == 0:
                raise ToolError("the PDF has no pages")
            if n == 1:
                ctx.progress(0.1, "rendering page 1 of 1")
                data = self._render_page(doc, 0, scale, pil_fmt)
                (ctx.output_dir / f"{src.stem}.{fmt}").write_bytes(data)
            else:
                # Render straight into the zip as ZIP_STORED: PNG/JPEG bytes are
                # already compressed, so DEFLATE + per-page temp files just waste
                # CPU and double the I/O.
                with zipfile.ZipFile(ctx.output_dir / f"{src.stem}-pages.zip", "w",
                                     zipfile.ZIP_STORED) as zf:
                    for i in range(n):
                        ctx.progress(i / n, f"rendering page {i + 1} of {n}")
                        data = self._render_page(doc, i, scale, pil_fmt)
                        zf.writestr(f"page_{i + 1:04d}.{fmt}", data)
        finally:
            doc.close()
        ctx.progress(1.0, "done")

    def _render_page(self, doc, index: int, scale: float, pil_fmt: str) -> bytes:
        page = doc[index]
        bitmap = page.render(scale=scale)
        try:
            pil = bitmap.to_pil()
            if pil_fmt == "JPEG":
                # Composite any alpha onto white BEFORE dropping the channel, or
                # transparent PDF regions come out black in the JPEG.
                if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
                    rgba = pil.convert("RGBA")
                    flat = Image.new("RGB", rgba.size, (255, 255, 255))
                    flat.paste(rgba, mask=rgba.split()[-1])
                    pil = flat
                elif pil.mode != "RGB":
                    pil = pil.convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, pil_fmt)
            return buf.getvalue()
        finally:
            try:
                bitmap.close()
            except Exception:
                pass
            try:
                page.close()
            except Exception:
                pass
