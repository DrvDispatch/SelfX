"""image-optimize: shrink an image's file size by re-encoding it efficiently (Pillow)."""

from PIL import Image

from .base import Tool, ToolContext, ToolError
from .registry import register

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover
    pass


@register
class ImageOptimize(Tool):
    slug = "image-optimize"
    name = "Optimize image"
    category = "images"
    description = "Reduce an image's file size by re-encoding it (keeps the same format)."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".heic", ".heif"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "quality": {
                "type": "integer",
                "title": "Quality",
                "description": "For lossy formats (jpg/webp)",
                "minimum": 1,
                "maximum": 100,
                "default": 75,
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        quality = int(ctx.params.get("quality", 75))
        src = ctx.input_paths[0]
        try:
            img = Image.open(src)
            img.load()
        except Exception:
            raise ToolError("the file is not a readable image") from None

        fmt = (img.format or "").upper()
        # normalise to a widely-supported output; keep the original extension where sensible
        if fmt in ("JPEG", "JPG", "MPO"):
            ext, save_fmt = "jpg", "JPEG"
            if img.mode != "RGB":
                img = img.convert("RGB")
            kw = {"quality": quality, "optimize": True, "progressive": True}
        elif fmt == "WEBP":
            ext, save_fmt, kw = "webp", "WEBP", {"quality": quality, "method": 6}
        else:  # PNG, TIFF, BMP, HEIC -> PNG (lossless, optimized)
            ext, save_fmt, kw = "png", "PNG", {"optimize": True}

        out = ctx.output_dir / f"{src.stem}-optimized.{ext}"
        img.save(out, save_fmt, **kw)
        img.close()
        before = src.stat().st_size
        after = out.stat().st_size
        pct = int((1 - after / before) * 100) if before else 0
        ctx.progress(1.0, f"optimized: {before} -> {after} bytes ({pct}% smaller)")
