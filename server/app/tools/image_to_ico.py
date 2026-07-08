"""image-to-ico: build a multi-resolution Windows .ico (favicon) from an image."""

from PIL import Image

from ._imaging import load_image
from .base import Tool, ToolContext, ToolError
from .registry import register

_ALLOWED_SIZES = [16, 24, 32, 48, 64, 128, 256]
_DEFAULT_SIZES = [16, 32, 48, 64, 128, 256]


@register
class ImageToIco(Tool):
    slug = "image-to-ico"
    name = "Image to icon (.ico)"
    category = "images"
    description = "Create a multi-size Windows icon / favicon (.ico) from any image."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "sizes": {
                "type": "array",
                "title": "Icon sizes (px)",
                "description": "Which square resolutions to include in the .ico",
                "items": {"type": "integer", "enum": _ALLOWED_SIZES},
                "default": _DEFAULT_SIZES,
            },
            "square_mode": {
                "type": "string",
                "title": "Non-square handling",
                "description": (
                    "keep = fit preserving aspect (default); "
                    "crop = centre-crop to a square; "
                    "pad = pad transparently to a square"
                ),
                "enum": ["keep", "crop", "pad"],
                "default": "keep",
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        # load_image applies EXIF orientation and guards against decompression bombs
        img = load_image(src)
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Validate the requested sizes against the allowed set, preserving order and
        # de-duplicating; fall back to the default set if nothing valid was passed.
        requested = ctx.params.get("sizes")
        selected: list[int] = []
        if isinstance(requested, list):
            for s in requested:
                try:
                    v = int(s)
                except (TypeError, ValueError):
                    continue
                if v in _ALLOWED_SIZES and v not in selected:
                    selected.append(v)
        if not selected:
            selected = list(_DEFAULT_SIZES)
        selected.sort()

        # Optionally square the source so every frame is an undistorted square.
        mode = str(ctx.params.get("square_mode", "keep"))
        if mode in ("crop", "pad") and img.width != img.height:
            w, h = img.width, img.height
            if mode == "crop":
                side = min(w, h)
                left, top = (w - side) // 2, (h - side) // 2
                img = img.crop((left, top, left + side, top + side))
            else:  # pad transparently to a square
                side = max(w, h)
                canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                canvas.paste(img, ((side - w) // 2, (side - h) // 2))
                img = canvas

        sizes = [(s, s) for s in selected]
        out = ctx.output_dir / f"{src.stem}.ico"
        ctx.progress(0.5, "building icon")
        img.save(out, format="ICO", sizes=sizes)
        img.close()
        if out.stat().st_size == 0:
            raise ToolError("icon creation failed")
        ctx.progress(1.0, "done")
