"""barcode-generate: create a 1D barcode (Code128, EAN-13, etc.) as PNG or SVG."""

from .base import Tool, ToolContext, ToolError
from .registry import register

# All of these are shipped by python-barcode (barcode.PROVIDED_BARCODES) and need
# no extra dependency. Retail/logistics symbologies (ITF, GS1-128, JAN, ...) are
# common real-world requests the tool previously refused.
_TYPES = [
    "code128", "code39", "ean13", "ean8", "ean14", "upca", "isbn13", "issn",
    "jan", "itf", "codabar", "gs1_128", "pzn", "nw-7",
]


@register
class BarcodeGenerate(Tool):
    slug = "barcode-generate"
    name = "Barcode"
    category = "utilities"
    description = "Generate a 1D barcode (Code128, EAN-13, UPC-A, ...) as a PNG or SVG image."
    accepts = []
    multi_file = False
    min_files = 0
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "data": {"type": "string", "title": "Data", "minLength": 1, "maxLength": 200},
            "type": {"type": "string", "title": "Symbology", "enum": _TYPES, "default": "code128"},
            "format": {"type": "string", "title": "Image format", "enum": ["png", "svg"],
                       "default": "png"},
            "dpi": {
                "type": "integer",
                "title": "DPI (PNG)",
                "description": "Raster resolution for print sharpness (PNG only; blank = default 300)",
                "minimum": 36,
                "maximum": 1200,
            },
            "module_width": {
                "type": "number",
                "title": "Bar width (mm)",
                "description": "Width of the narrowest bar in mm (blank = default 0.2)",
                "minimum": 0.05,
                "maximum": 5,
            },
            "module_height": {
                "type": "number",
                "title": "Bar height (mm)",
                "description": "Height of the bars in mm (blank = default 15)",
                "minimum": 1,
                "maximum": 200,
            },
            "quiet_zone": {
                "type": "number",
                "title": "Quiet zone (mm)",
                "description": "Blank margin on each side in mm (blank = default 6.5)",
                "minimum": 0,
                "maximum": 50,
            },
            "font_size": {
                "type": "integer",
                "title": "Text size (pt)",
                "description": "Human-readable text size in pt (blank = default 10)",
                "minimum": 1,
                "maximum": 100,
            },
            "write_text": {
                "type": "boolean",
                "title": "Show human-readable text",
                "description": "Draw the encoded value beneath the bars",
                "default": True,
            },
            "foreground": {
                "type": "string",
                "title": "Bar color",
                "description": "Bar/text color as a name or #RRGGBB hex (blank = black)",
                "maxLength": 32,
            },
            "background": {
                "type": "string",
                "title": "Background color",
                "description": "Background color as a name or #RRGGBB hex (blank = white)",
                "maxLength": 32,
            },
        },
        "required": ["data"],
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import barcode  # noqa: F401
            return True, None
        except Exception:
            return False, "the barcode engine (python-barcode) is not installed"

    def _build_options(self, ctx: ToolContext, fmt: str) -> dict:
        """Collect only the WriterOptions the caller actually set, so unspecified
        knobs keep python-barcode's defaults (backward compatible)."""
        p = ctx.params
        options: dict = {}
        # dpi only affects the raster ImageWriter; harmless to omit for SVG.
        if fmt == "png" and p.get("dpi") is not None:
            options["dpi"] = max(36, min(1200, int(p["dpi"])))
        if p.get("module_width") is not None:
            options["module_width"] = max(0.05, min(5.0, float(p["module_width"])))
        if p.get("module_height") is not None:
            options["module_height"] = max(1.0, min(200.0, float(p["module_height"])))
        if p.get("quiet_zone") is not None:
            options["quiet_zone"] = max(0.0, min(50.0, float(p["quiet_zone"])))
        if p.get("font_size") is not None:
            options["font_size"] = max(1, min(100, int(p["font_size"])))
        # write_text defaults to True in python-barcode; only pass when turning it off.
        if p.get("write_text") is False:
            options["write_text"] = False
        if p.get("foreground"):
            options["foreground"] = str(p["foreground"])
        if p.get("background"):
            options["background"] = str(p["background"])
        return options

    def run(self, ctx: ToolContext) -> None:
        import barcode
        from barcode.writer import ImageWriter, SVGWriter

        data = str(ctx.params["data"])
        code_type = str(ctx.params.get("type", "code128"))
        fmt = str(ctx.params.get("format", "png"))
        if code_type not in _TYPES:
            raise ToolError(f"unsupported barcode type '{code_type}'")

        writer = ImageWriter() if fmt == "png" else SVGWriter()
        try:
            cls = barcode.get_barcode_class(code_type)
            obj = cls(data, writer=writer)
        except Exception:
            hint = " — Code39 data must be uppercase" if code_type == "code39" else ""
            raise ToolError(
                f"'{data}' is not valid for a {code_type} barcode "
                f"(check the required digits/characters){hint}"
            ) from None

        options = self._build_options(ctx, fmt)
        # .save() renders the image; the PNG path needs Pillow (and its bundled
        # font). This runs OUTSIDE the validation try above, so wrap it too or a
        # missing Pillow becomes an uncaught 'internal error'.
        try:
            saved = obj.save(str(ctx.output_dir / "barcode"), options=options or None)
        except ImportError:
            raise ToolError(
                "PNG barcode rendering requires the Pillow library, which is not "
                "installed — try the SVG format instead"
            ) from None
        except Exception:
            raise ToolError("barcode image rendering failed") from None
        if not saved:
            raise ToolError("barcode generation failed")
        ctx.progress(1.0, "done")
