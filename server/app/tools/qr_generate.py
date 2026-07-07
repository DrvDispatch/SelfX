"""qr-generate: QR code image from text with segno (SPEC §8; param-only, min_files=0)."""

import segno

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class QrGenerate(Tool):
    slug = "qr-generate"
    name = "QR code"
    category = "utilities"
    description = "Generate a QR code image (PNG or SVG) from text or a URL."
    accepts = []
    multi_file = False
    min_files = 0
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "title": "Text",
                "description": "Text or URL to encode in the QR code",
                "minLength": 1,
                "maxLength": 2000,
            },
            "format": {
                "type": "string",
                "title": "Format",
                "enum": ["png", "svg"],
                "default": "png",
            },
            "scale": {
                "type": "integer",
                "title": "Scale",
                "description": "Pixel size of each QR module",
                "minimum": 1,
                "maximum": 50,
                "default": 8,
            },
        },
        "required": ["text"],
    }

    def run(self, ctx: ToolContext) -> None:
        text = str(ctx.params["text"])
        fmt = str(ctx.params.get("format", "png"))
        scale = int(ctx.params.get("scale", 8))
        ctx.progress(0.2, "generating QR code")
        try:
            qr = segno.make(text, error="m")
        except ValueError:
            raise ToolError("the text is too long to fit in a QR code") from None
        out_path = ctx.output_dir / f"qr.{fmt}"
        qr.save(str(out_path), scale=scale)
        ctx.progress(1.0, f"saved qr.{fmt}")
