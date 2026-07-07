"""pdf-to-images: render each PDF page to an image with PDFium (permissive)."""

import zipfile

import pypdfium2 as pdfium

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
            rendered: list = []
            for i in range(n):
                ctx.progress(i / n, f"rendering page {i + 1} of {n}")
                bitmap = doc[i].render(scale=scale)
                pil = bitmap.to_pil()
                if pil_fmt == "JPEG":
                    pil = pil.convert("RGB")
                out = ctx.workdir / f"page_{i + 1:04d}.{fmt}"
                pil.save(out, pil_fmt)
                rendered.append(out)
            if len(rendered) == 1:
                target = ctx.output_dir / f"{src.stem}.{fmt}"
                rendered[0].replace(target)
            else:
                ctx.progress(0.95, "zipping pages")
                with zipfile.ZipFile(ctx.output_dir / f"{src.stem}-pages.zip", "w",
                                     zipfile.ZIP_DEFLATED) as zf:
                    for p in rendered:
                        zf.write(p, arcname=p.name)
        finally:
            doc.close()
        ctx.progress(1.0, "done")
