"""image-to-ico: build a multi-resolution Windows .ico (favicon) from an image."""

from ._imaging import load_image
from .base import Tool, ToolContext, ToolError
from .registry import register


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
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        # load_image applies EXIF orientation and guards against decompression bombs
        img = load_image(src)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        out = ctx.output_dir / f"{src.stem}.ico"
        ctx.progress(0.5, "building icon")
        img.save(out, format="ICO", sizes=sizes)
        img.close()
        if out.stat().st_size == 0:
            raise ToolError("icon creation failed")
        ctx.progress(1.0, "done")
