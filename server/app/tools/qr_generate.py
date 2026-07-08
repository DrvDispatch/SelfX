"""qr-generate: QR code image from text with segno (SPEC §8; param-only, min_files=0)."""

import segno

from .base import Tool, ToolContext, ToolError
from .registry import register

# segno.save() infers the writer from the extension; all of these are native
# segno kinds and need no extra dependency.
_FORMATS = ["png", "svg", "pdf", "eps", "txt"]
_ERROR_LEVELS = ["l", "m", "q", "h"]


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
                "enum": _FORMATS,
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
            "error": {
                "type": "string",
                "title": "Error correction",
                "description": (
                    "Redundancy level: L ~7%, M ~15%, Q ~25%, H ~30%. "
                    "Higher survives more damage / allows logo overlay but holds less data."
                ),
                "enum": _ERROR_LEVELS,
                "default": "m",
            },
            "border": {
                "type": "integer",
                "title": "Quiet-zone border",
                "description": "Width of the light border in modules (blank = format default, 4)",
                "minimum": 0,
                "maximum": 100,
            },
            "dark": {
                "type": "string",
                "title": "Foreground color",
                "description": "Module (dark) color as a name or #RRGGBB hex (blank = black)",
                "maxLength": 32,
            },
            "light": {
                "type": "string",
                "title": "Background color",
                "description": "Background (light) color as a name, #RRGGBB, or 'transparent'",
                "maxLength": 32,
            },
            "micro": {
                "type": "string",
                "title": "Micro QR",
                "description": (
                    "auto = pick the most compact symbol (default); "
                    "no = force a full QR; yes = force a Micro QR (tiny payloads only)"
                ),
                "enum": ["auto", "no", "yes"],
                "default": "auto",
            },
            "boost_error": {
                "type": "boolean",
                "title": "Boost error correction",
                "description": "Raise the error level automatically when there is spare capacity",
                "default": True,
            },
        },
        "required": ["text"],
    }

    def run(self, ctx: ToolContext) -> None:
        text = str(ctx.params["text"])
        fmt = str(ctx.params.get("format", "png"))
        if fmt not in _FORMATS:
            raise ToolError(f"unsupported QR format '{fmt}'")
        scale = int(ctx.params.get("scale", 8))
        scale = max(1, min(50, scale))
        error = str(ctx.params.get("error", "m")).lower()
        if error not in _ERROR_LEVELS:
            raise ToolError(f"unsupported error-correction level '{error}'")
        boost = bool(ctx.params.get("boost_error", True))
        micro_choice = str(ctx.params.get("micro", "auto")).lower()

        make_kw: dict = {"error": error, "boost_error": boost}
        # 'auto' preserves segno's default symbol selection (may pick a Micro QR
        # for tiny inputs); only pin micro when the caller explicitly asks.
        if micro_choice == "yes":
            make_kw["micro"] = True
        elif micro_choice == "no":
            make_kw["micro"] = False

        ctx.progress(0.2, "generating QR code")
        try:
            qr = segno.make(text, **make_kw)
        except ValueError:
            raise ToolError("the text is too long to fit in a QR code") from None

        save_kw: dict = {"scale": scale}
        border = ctx.params.get("border")
        if border is not None:
            save_kw["border"] = max(0, min(100, int(border)))
        dark = ctx.params.get("dark")
        if dark:
            save_kw["dark"] = str(dark)
        light = ctx.params.get("light")
        if light is not None and str(light) != "":
            # 'transparent' is a valid segno light value; pass strings through.
            save_kw["light"] = None if str(light).lower() == "transparent" else str(light)

        out_path = ctx.output_dir / f"qr.{fmt}"
        try:
            qr.save(str(out_path), **save_kw)
        except ValueError as exc:
            raise ToolError(f"could not render the QR code: {exc}") from None
        ctx.progress(1.0, f"saved qr.{fmt}")
