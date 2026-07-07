"""images-to-pdf: combine one or more images into a single PDF (img2pdf, lossless)."""

import img2pdf
from PIL import Image

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
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        prepared: list[str] = []
        total = len(ctx.input_paths)
        for i, path in enumerate(ctx.input_paths):
            ctx.progress(i / total, f"preparing image {i + 1} of {total}")
            try:
                img = Image.open(path)
                img.load()
            except Exception:
                raise ToolError(f"file #{i + 1} is not a readable image") from None
            # img2pdf rejects alpha; flatten onto white and normalise to RGB JPEG
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            tmp = ctx.workdir / f"img_{i:04d}.jpg"
            img.save(tmp, "JPEG", quality=90)
            img.close()
            prepared.append(str(tmp))
        ctx.progress(0.9, "building PDF")
        with (ctx.output_dir / "images.pdf").open("wb") as fh:
            fh.write(img2pdf.convert(prepared))
        ctx.progress(1.0, "done")
