"""image-optimize: shrink an image's file size by re-encoding it efficiently (Pillow)."""

from contextlib import ExitStack
from io import BytesIO
from shutil import copyfile

from PIL import Image

from ._imaging import flatten_rgb, load_image
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
    description = "Reduce an image's file size. JPEG and WebP can use a strict size limit."
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
            },
            "target_kb": {
                "type": "integer",
                "title": "Target size (KB)",
                "description": (
                    "For JPEG/WebP inputs, lower the quality automatically to fit "
                    "under this size; leave blank to just use the quality above"
                ),
                "minimum": 1,
                "maximum": 100000,
            },
            "png_compress_level": {
                "type": "integer",
                "title": "PNG compression level",
                "description": "0 = fast/large .. 9 = slow/small; leave blank for default",
                "minimum": 0,
                "maximum": 9,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        quality = int(ctx.params.get("quality", 75))
        target_kb = ctx.params.get("target_kb")
        target = int(target_kb) * 1024 if target_kb else None
        src = ctx.input_paths[0]
        before = src.stat().st_size
        # Determine the true source format from the file header BEFORE load_image:
        # load_image bakes in EXIF orientation via ImageOps.exif_transpose, which
        # always returns a fresh copy whose .format is None. Reading img.format after
        # that would therefore always be empty and force every input down the PNG
        # branch (silently transcoding JPEG/WebP to a larger PNG). Probe here instead.
        try:
            with Image.open(src) as probe:
                fmt = (probe.format or "").upper()
        except Exception:
            fmt = ""
        # load_image applies EXIF orientation and guards against decompression bombs
        # normalise to a widely-supported output; keep the original extension where sensible
        if fmt in ("JPEG", "JPG", "MPO"):
            ext, save_fmt = "jpg", "JPEG"
            kw = {"quality": quality, "optimize": True, "progressive": True}
        elif fmt == "WEBP":
            ext, save_fmt, kw = "webp", "WEBP", {"quality": quality, "method": 6}
        else:  # PNG, TIFF, BMP, HEIC -> PNG (lossless, optimized)
            ext, save_fmt, kw = "png", "PNG", {"optimize": True}
            cl = ctx.params.get("png_compress_level")
            if cl is not None:
                try:
                    kw["compress_level"] = max(0, min(9, int(cl)))
                except (TypeError, ValueError):
                    pass

        out = ctx.output_dir / f"{src.stem}-optimized.{ext}"
        original = ctx.output_dir / f"{src.stem}-optimized{src.suffix.lower()}"
        if target and save_fmt not in ("JPEG", "WEBP"):
            raise ToolError("A target size needs a JPEG or WebP input. Convert this image first.")

        with ExitStack() as stack:
            img = stack.enter_context(load_image(src))
            if target and before <= target:
                copyfile(src, original)
                ctx.progress(1.0, f"original already fits under {target_kb} KB")
                return
            if save_fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = stack.enter_context(flatten_rgb(img))
            if target:
                out.write_bytes(_fit_target(img, save_fmt, kw, quality, target))
            else:
                img.save(out, save_fmt, **kw)
        after = out.stat().st_size

        if before and after >= before:
            copyfile(src, original)
            if original != out:
                out.unlink(missing_ok=True)
            ctx.progress(1.0, f"already optimal: kept original ({before} bytes)")
            return

        pct = int((1 - after / before) * 100) if before else 0
        ctx.progress(1.0, f"optimized: {before} -> {after} bytes ({pct}% smaller)")


def _fit_target(img, save_fmt: str, options: dict, quality: int, target: int) -> bytes:
    def encode(quality: int) -> bytes:
        with BytesIO() as buffer:
            img.save(buffer, save_fmt, **{**options, "quality": quality})
            return buffer.getvalue()

    full = encode(quality)
    if len(full) <= target:
        return full
    best = None
    lower, upper = 1, quality - 1
    while lower <= upper:
        mid = (lower + upper) // 2
        candidate = encode(mid)
        if len(candidate) <= target:
            best = candidate
            lower = mid + 1
        else:
            upper = mid - 1
    if best is None:
        raise ToolError("This image cannot fit under the chosen limit. Resize it or increase the limit.")
    return best
