"""image-convert: convert / resize / recompress images with Pillow (SPEC §8).

pillow-heif is registered so HEIC/HEIF inputs open. AVIF support depends on the
Pillow build; if the running Pillow can't encode AVIF we raise a clear message.
"""

from PIL import Image

from ._imaging import flatten_rgb, load_image
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
            "max_height": {
                "type": "integer",
                "title": "Max height (px)",
                "description": "Scale down if taller than this; leave blank to keep size",
                "minimum": 1,
                "maximum": 20000,
            },
            "strip_metadata": {
                "type": "boolean",
                "title": "Strip metadata",
                "default": True,
            },
            "to_srgb": {
                "type": "boolean",
                "title": "Convert to sRGB",
                "description": (
                    "When stripping metadata, convert wide-gamut images to sRGB "
                    "first so colours don't shift once the ICC profile is dropped"
                ),
                "default": False,
            },
            "lossless": {
                "type": "boolean",
                "title": "Lossless (WebP)",
                "description": "Encode WebP losslessly (ignores quality)",
                "default": False,
            },
            "webp_method": {
                "type": "integer",
                "title": "WebP effort",
                "description": "0 = fast/larger .. 6 = slow/smallest",
                "minimum": 0,
                "maximum": 6,
                "default": 4,
            },
            "subsampling": {
                "type": "string",
                "title": "JPEG chroma subsampling",
                "description": "auto = Pillow default; 4:4:4 keeps full colour detail",
                "enum": ["auto", "4:4:4", "4:2:2", "4:2:0"],
                "default": "auto",
            },
            "png_optimize": {
                "type": "boolean",
                "title": "Optimise PNG",
                "description": "Extra lossless PNG compression pass (slower, smaller)",
                "default": False,
            },
            "png_compress_level": {
                "type": "integer",
                "title": "PNG compression level",
                "description": "0 = fast/large .. 9 = slow/small; leave blank for default",
                "minimum": 0,
                "maximum": 9,
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
        max_height = ctx.params.get("max_height")
        strip = bool(ctx.params.get("strip_metadata", True))
        to_srgb = bool(ctx.params.get("to_srgb", False))

        src = ctx.input_paths[0]
        ctx.progress(0.2, "reading image")
        # load_image applies EXIF orientation and guards against decompression bombs
        img = load_image(src)

        # When the caller wants the ICC profile dropped (strip=True) but opts in to
        # sRGB conversion, remap the pixels through the embedded profile first so a
        # wide-gamut phone photo doesn't visibly desaturate once the profile is gone.
        if to_srgb and strip:
            icc = img.info.get("icc_profile")
            if icc:
                try:
                    from io import BytesIO

                    from PIL import ImageCms

                    src_profile = ImageCms.ImageCmsProfile(BytesIO(icc))
                    dst_profile = ImageCms.createProfile("sRGB")
                    out_mode = "RGB" if img.mode not in ("RGBA", "LA") else "RGBA"
                    converted = ImageCms.profileToProfile(
                        img, src_profile, dst_profile, outputMode=out_mode
                    )
                    if converted is not None:
                        img = converted
                        img.info.pop("icc_profile", None)
                except Exception:
                    pass  # best-effort: fall back to plain strip on any failure

        # flatten alpha onto white for formats that don't support it (no black JPEG)
        if pil_fmt in ("JPEG", "BMP"):
            img = flatten_rgb(img)
        elif img.mode == "P":
            img = img.convert("RGBA")

        # Scale down to fit within max_width / max_height (either may be set),
        # preserving aspect ratio; only ever downscale, never enlarge.
        def _int(val: object) -> int:
            try:
                return int(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0

        mw, mh = _int(max_width), _int(max_height)
        scale = 1.0
        if mw > 0 and img.width > mw:
            scale = min(scale, mw / img.width)
        if mh > 0 and img.height > mh:
            scale = min(scale, mh / img.height)
        if scale < 1.0:
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            ctx.progress(0.5, f"resizing to {new_size[0]}x{new_size[1]}")
            img = img.resize(new_size, Image.LANCZOS)

        save_kw: dict = {}
        if pil_fmt in ("JPEG", "WEBP", "AVIF"):
            save_kw["quality"] = quality
        if pil_fmt == "WEBP":
            save_kw["method"] = max(0, min(6, int(ctx.params.get("webp_method", 4))))
            if bool(ctx.params.get("lossless", False)):
                save_kw["lossless"] = True
        if pil_fmt == "JPEG":
            sub = str(ctx.params.get("subsampling", "auto"))
            sub_map = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}
            if sub in sub_map:
                save_kw["subsampling"] = sub_map[sub]
        if pil_fmt == "PNG":
            if bool(ctx.params.get("png_optimize", False)):
                save_kw["optimize"] = True
            cl = ctx.params.get("png_compress_level")
            if cl is not None:
                save_kw["compress_level"] = max(0, min(9, _int(cl)))
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
