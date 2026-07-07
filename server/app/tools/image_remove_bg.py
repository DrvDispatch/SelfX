"""image-remove-bg: remove an image background with rembg (U^2-Net, CPU/ONNX)."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class ImageRemoveBg(Tool):
    slug = "image-remove-bg"
    name = "Remove background"
    category = "images"
    description = "Automatically remove the background from a photo, leaving a transparent PNG."
    accepts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "title": "Model",
                "description": "u2net = general, isnet-general-use = higher quality",
                "enum": ["u2net", "isnet-general-use", "u2netp", "silueta"],
                "default": "u2net",
            }
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import rembg  # noqa: F401
            return True, None
        except Exception:
            return False, "the background-removal engine (rembg) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from rembg import new_session, remove

        model = str(ctx.params.get("model", "u2net"))
        src = ctx.input_paths[0]
        ctx.progress(0.3, "removing background (first run downloads the model)")
        try:
            session = new_session(model)
            data = remove(src.read_bytes(), session=session)
        except Exception:
            raise ToolError("background removal failed — the image may be unsupported") from None
        out = ctx.output_dir / f"{src.stem}-nobg.png"
        out.write_bytes(data)
        if out.stat().st_size == 0:
            raise ToolError("background removal produced no output")
        ctx.progress(1.0, "done")
