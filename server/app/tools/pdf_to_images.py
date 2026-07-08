"""pdf-to-images: render each PDF page to an image with PDFium (permissive)."""

import io
import zipfile

import pypdfium2 as pdfium
from PIL import Image

from .base import Tool, ToolContext, ToolError
from .registry import register

# Refuse to rasterize a single page larger than this many pixels (width*height
# at the chosen DPI). A huge MediaBox at 600 DPI can otherwise OOM the CPU-only
# worker. Generous vs the 64 MP image guard because posters/plans legitimately
# render large, but still a hard ceiling on peak RAM.
_MAX_PIXELS = 120_000_000

_FMT = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}


@register
class PdfToImages(Tool):
    slug = "pdf-to-images"
    name = "PDF to images"
    category = "pdf"
    description = "Render each page of a PDF to a PNG, JPEG or WebP image (returned as a zip for multi-page)."
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
                "enum": ["png", "jpg", "webp"],
                "default": "png",
            },
            "dpi": {
                "type": "integer",
                "title": "Resolution (DPI)",
                "minimum": 36,
                "maximum": 600,
                "default": 150,
            },
            "quality": {
                "type": "integer",
                "title": "JPEG / WebP quality",
                "description": "1–100; higher is sharper but larger (JPEG/WebP only).",
                "minimum": 1,
                "maximum": 100,
                "default": 85,
            },
            "grayscale": {
                "type": "boolean",
                "title": "Grayscale",
                "description": "Render in black & white — smaller and sharper for text scans.",
                "default": False,
            },
            "first_page": {
                "type": "integer",
                "title": "First page",
                "description": "1-based first page to render (blank = from the start).",
                "minimum": 1,
            },
            "last_page": {
                "type": "integer",
                "title": "Last page",
                "description": "1-based last page to render (blank = to the end).",
                "minimum": 1,
            },
            "password": {
                "type": "string",
                "title": "PDF password",
                "description": "Only needed if the PDF is password-protected.",
                "maxLength": 128,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "png"))
        pil_fmt = _FMT.get(fmt, "PNG")
        if pil_fmt == "PNG":
            fmt = "png"
        dpi = max(36, min(600, int(ctx.params.get("dpi", 150))))
        scale = dpi / 72.0
        quality = max(1, min(100, int(ctx.params.get("quality", 85))))
        grayscale = bool(ctx.params.get("grayscale", False))
        password = str(ctx.params.get("password") or "") or None
        src = ctx.input_paths[0]
        try:
            doc = pdfium.PdfDocument(str(src), password=password)
        except Exception:
            raise ToolError(
                "the input is not a valid PDF file, or it is password-protected "
                "(supply the password)"
            ) from None
        try:
            n = len(doc)
            if n == 0:
                raise ToolError("the PDF has no pages")

            # Optional 1-based page range → 0-based [start, end) window.
            first = ctx.params.get("first_page")
            last = ctx.params.get("last_page")
            start = (int(first) - 1) if first else 0
            end = int(last) if last else n
            start = max(0, start)
            end = min(n, end)
            if start >= end:
                raise ToolError("the selected page range is empty or out of order")
            indices = list(range(start, end))

            if len(indices) == 1:
                idx = indices[0]
                ctx.progress(0.1, f"rendering page {idx + 1}")
                data = self._render_page(doc, idx, scale, pil_fmt, quality, grayscale)
                (ctx.output_dir / f"{src.stem}.{fmt}").write_bytes(data)
            else:
                # Render straight into the zip as ZIP_STORED: PNG/JPEG/WebP bytes
                # are already compressed, so DEFLATE + per-page temp files just
                # waste CPU and double the I/O.
                total = len(indices)
                with zipfile.ZipFile(ctx.output_dir / f"{src.stem}-pages.zip", "w",
                                     zipfile.ZIP_STORED) as zf:
                    for j, idx in enumerate(indices):
                        ctx.progress(j / total, f"rendering page {idx + 1} ({j + 1} of {total})")
                        data = self._render_page(doc, idx, scale, pil_fmt, quality, grayscale)
                        zf.writestr(f"page_{idx + 1:04d}.{fmt}", data)
        finally:
            doc.close()
        ctx.progress(1.0, "done")

    def _render_page(self, doc, index: int, scale: float, pil_fmt: str,
                     quality: int, grayscale: bool) -> bytes:
        page = doc[index]
        try:
            # Bound peak RAM before we allocate the raster buffer.
            try:
                w_pt, h_pt = page.get_size()
                if (w_pt * scale) * (h_pt * scale) > _MAX_PIXELS:
                    raise ToolError(
                        f"page {index + 1} is too large to render at {int(scale * 72)} DPI — "
                        "lower the resolution"
                    )
            except ToolError:
                raise
            except Exception:
                pass
            bitmap = page.render(scale=scale, grayscale=grayscale)
            try:
                pil = bitmap.to_pil()
                if pil_fmt == "JPEG":
                    # Composite any alpha onto white BEFORE dropping the channel,
                    # or transparent PDF regions come out black in the JPEG.
                    if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
                        rgba = pil.convert("RGBA")
                        flat = Image.new("RGB", rgba.size, (255, 255, 255))
                        flat.paste(rgba, mask=rgba.split()[-1])
                        pil = flat
                    elif pil.mode not in ("RGB", "L"):
                        pil = pil.convert("RGB")
                    save_kw = {"quality": quality, "optimize": True, "progressive": True}
                elif pil_fmt == "WEBP":
                    # Pillow's WebP encoder wants RGB/RGBA; keep alpha, else RGB.
                    if pil.mode not in ("RGB", "RGBA"):
                        pil = pil.convert("RGB")
                    save_kw = {"quality": quality}
                else:  # PNG — lossless; optimize only shrinks the file, same pixels
                    save_kw = {"optimize": True}
                buf = io.BytesIO()
                pil.save(buf, pil_fmt, **save_kw)
                return buf.getvalue()
            finally:
                try:
                    bitmap.close()
                except Exception:
                    pass
        finally:
            try:
                page.close()
            except Exception:
                pass
