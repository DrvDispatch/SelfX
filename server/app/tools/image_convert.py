"""image-convert: convert / resize / recompress images with Pillow (SPEC §8).

pillow-heif is registered so HEIC/HEIF inputs open. AVIF support depends on the
Pillow build; if the running Pillow can't encode AVIF we raise a clear message.
"""

from PIL import Image

from .base import Tool, ToolContext, ToolError
from .registry import register

try:  # register the HEIF/HEIC opener at import time
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - HEIC just won't be available
    pass

# target format -> (Pillow format name, file extension)
_FORMATS = {
    "png": ("PNG", "png"),
    "jpg": ("JPEG", "jpg"),
    "webp": ("WEBP", "webp"),
    "avif": ("AVIF", "avif"),
    "bmp": ("BMP", "bmp"),
    "tiff": ("TIFF", "tiff"),
}


@register
class ImageConvert(Tool):
    slug = "image-convert"
    name = "Image convert / resize"
    category = "images"
    description = "Convert an image to another format, optionally resizing and stripping metadata."
    accepts = [
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
        ".tiff", ".tif", ".heic", ".heif", ".avif",
    ]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "title": "Output format",
                "enum": ["png", "jpg", "webp", "avif", "bmp", "tiff"],
                "default": "png",
            },
            "quality": {
                "type": "integer",
                "title": "Quality",
                "description": "For lossy formats (jpg/webp/avif)",
                "minimum": 1,
                "maximum": 100,
                "default": 85,
            },
            "max_width": {
                "type": "integer",
                "title": "Max width (px)",
                "description": "Scale down if wider than this; leave blank to keep size",
                "minimum": 1,
                "maximum": 20000,
            },
            "strip_metadata": {
                "type": "boolean",
                "title": "Strip metadata",
                "default": True,
            },
        },
        "required": ["format"],
    }

    def run(self, ctx: ToolContext) -> None:
        fmt = str(ctx.params.get("format", "png"))
        pil_fmt, ext = _FORMATS.get(fmt, (None, None))
        if pil_fmt is None:
            raise ToolError(f"unsupported output format '{fmt}'")
        quality = int(ctx.params.get("quality", 85))
        max_width = ctx.params.get("max_width")
        strip = bool(ctx.params.get("strip_metadata", True))

        src = ctx.input_paths[0]
        ctx.progress(0.2, "reading image")
        try:
            img = Image.open(src)
            img.load()
        except Exception:
            raise ToolError("the file is not a readable image") from None

        # flatten alpha for formats that don't support it
        if pil_fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode == "P":
            img = img.convert("RGBA")

        if max_width:
            try:
                mw = int(max_width)
            except (TypeError, ValueError):
                mw = 0
            if mw > 0 and img.width > mw:
                ratio = mw / img.width
                new_size = (mw, max(1, round(img.height * ratio)))
                ctx.progress(0.5, f"resizing to {new_size[0]}px wide")
                img = img.resize(new_size, Image.LANCZOS)

        save_kw: dict = {}
        if pil_fmt in ("JPEG", "WEBP", "AVIF"):
            save_kw["quality"] = quality
        if not strip:
            exif = img.info.get("exif")
            if exif:
                save_kw["exif"] = exif
            icc = img.info.get("icc_profile")
            if icc:
                save_kw["icc_profile"] = icc

        out_path = ctx.output_dir / f"{src.stem}.{ext}"
        ctx.progress(0.8, f"saving {fmt}")
        try:
            img.save(out_path, format=pil_fmt, **save_kw)
        except (KeyError, OSError, ValueError):
            if fmt == "avif":
                raise ToolError(
                    "AVIF encoding isn't supported by this server's image library — "
                    "try WebP instead"
                ) from None
            raise ToolError(f"could not encode the image as {fmt}") from None
        finally:
            img.close()
        ctx.progress(1.0, "done")
