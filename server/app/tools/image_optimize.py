"""image-optimize: shrink an image's file size by re-encoding it efficiently (Pillow)."""

from io import BytesIO

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
        src = ctx.input_paths[0]
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
        img = load_image(src)
        # normalise to a widely-supported output; keep the original extension where sensible
        if fmt in ("JPEG", "JPG", "MPO"):
            ext, save_fmt = "jpg", "JPEG"
            # keep single-channel greyscale as L (RGB would triple the size); only
            # normalise alpha / palette / CMYK to RGB, compositing onto white.
            if img.mode not in ("RGB", "L"):
                img = flatten_rgb(img)
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

        # Optional target-size mode: for lossy formats, binary-search the highest
        # quality whose encoded size fits under target_kb. Falls back to the lowest
        # quality if even that overshoots. Lossless PNG has no quality knob, so it
        # is left untouched by this loop.
        chosen_bytes = None
        if target_kb and save_fmt in ("JPEG", "WEBP"):
            try:
                target_bytes = int(target_kb) * 1024
            except (TypeError, ValueError):
                target_bytes = 0
            if target_bytes > 0:
                def _encode(q: int) -> bytes:
                    buf = BytesIO()
                    img.save(buf, save_fmt, **{**kw, "quality": max(1, min(100, q))})
                    return buf.getvalue()

                lo, hi = 5, quality
                best = None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    data = _encode(mid)
                    if len(data) <= target_bytes:
                        best = data
                        lo = mid + 1
                    else:
                        hi = mid - 1
                chosen_bytes = best if best is not None else _encode(5)

        if chosen_bytes is not None:
            out.write_bytes(chosen_bytes)
        else:
            img.save(out, save_fmt, **kw)
        img.close()
        before = src.stat().st_size
        after = out.stat().st_size

        # Never hand back a bigger file than the input: if the re-encode didn't
        # actually shrink it, return the original bytes unchanged instead.
        if before and after >= before:
            orig_ext = (src.suffix.lstrip(".").lower() or ext)
            fallback = ctx.output_dir / f"{src.stem}-optimized.{orig_ext}"
            fallback.write_bytes(src.read_bytes())
            if fallback != out:
                out.unlink(missing_ok=True)
            after = fallback.stat().st_size
            ctx.progress(1.0, f"already optimal: kept original ({before} bytes)")
            return

        pct = int((1 - after / before) * 100) if before else 0
        ctx.progress(1.0, f"optimized: {before} -> {after} bytes ({pct}% smaller)")
