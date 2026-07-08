"""images-to-pdf: combine one or more images into a single PDF (img2pdf, lossless)."""

import img2pdf
from PIL import Image

from ._docutil import validate_pdf_output
from ._imaging import flatten_rgb, load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover
    pass


@register
class ImagesToPdf(Tool):
    slug = "images-to-pdf"
    name = "Images to PDF"
    category = "images"
    description = "Combine images into one PDF, one image per page, in upload order."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif", ".gif"]
    multi_file = True
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "lossless": {
                "type": "boolean",
                "title": "Lossless (no recompression)",
                "description": "Embed already-compatible JPEG/PNG images without re-encoding "
                               "— crisper text/line-art and no generational quality loss.",
                "default": False,
            },
            "quality": {
                "type": "integer",
                "title": "JPEG quality",
                "description": "1–100, used when an image must be re-encoded.",
                "minimum": 1,
                "maximum": 100,
                "default": 90,
            },
            "dpi": {
                "type": "integer",
                "title": "DPI",
                "description": "Physical resolution for page sizing (blank = derive from pixels).",
                "minimum": 1,
                "maximum": 1200,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        lossless = bool(ctx.params.get("lossless", False))
        quality = max(1, min(100, int(ctx.params.get("quality", 90))))
        dpi_param = ctx.params.get("dpi")
        dpi = max(1, min(1200, int(dpi_param))) if dpi_param else None

        items: list[str] = []
        total = len(ctx.input_paths)
        for i, path in enumerate(ctx.input_paths):
            ctx.progress(i / total, f"preparing image {i + 1} of {total}")
            # Fast path: embed the original bytes losslessly when the image is
            # already in an img2pdf-friendly form and correctly oriented.
            if lossless and self._embeddable(path):
                items.append(str(path))
                continue
            # load_image applies EXIF orientation (no sideways pages) and the
            # decompression-bomb guard; prefix the file index onto its message
            try:
                img = load_image(path)
            except ToolError as exc:
                raise ToolError(f"file #{i + 1}: {exc}") from None
            # img2pdf rejects alpha; flatten onto white and normalise to RGB JPEG
            img = flatten_rgb(img)
            tmp = ctx.workdir / f"img_{i:04d}.jpg"
            img.save(tmp, "JPEG", quality=quality)
            img.close()
            items.append(str(tmp))

        ctx.progress(0.9, "building PDF")
        out = ctx.output_dir / "images.pdf"
        convert_kw = {}
        if dpi:
            convert_kw["dpi"] = dpi
        with out.open("wb") as fh:
            fh.write(img2pdf.convert(items, **convert_kw))
        validate_pdf_output(out, min_pages=1)
        ctx.progress(1.0, "done")

    @staticmethod
    def _embeddable(path) -> bool:
        """True only for images img2pdf can embed byte-for-byte, correctly oriented.

        Conservative on purpose: baseline JPEG (RGB/grayscale, no EXIF rotation,
        not progressive) and non-transparent PNG (RGB/grayscale). Anything with
        alpha, CMYK, palette-transparency, or an orientation flag falls through
        to the re-encode path where those are handled.
        """
        try:
            with Image.open(path) as im:
                fmt = im.format
                mode = im.mode
                info = dict(im.info)
                exif = im.getexif()
                orient = int(exif.get(274, 1)) if exif else 1
        except Exception:
            return False
        if orient not in (0, 1):
            return False
        if fmt == "JPEG":
            if info.get("progressive") or info.get("progression"):
                return False
            return mode in ("RGB", "L")
        if fmt == "PNG":
            if "transparency" in info:
                return False
            return mode in ("RGB", "L")
        return False
