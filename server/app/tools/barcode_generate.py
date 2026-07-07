"""barcode-generate: create a 1D barcode (Code128, EAN-13, etc.) as PNG or SVG."""

from .base import Tool, ToolContext, ToolError
from .registry import register

_TYPES = ["code128", "code39", "ean13", "ean8", "upca", "isbn13", "issn"]


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
        },
        "required": ["data"],
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import barcode  # noqa: F401
            return True, None
        except Exception:
            return False, "the barcode engine (python-barcode) is not installed"

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
            raise ToolError(
                f"'{data}' is not valid for a {code_type} barcode (check the required digits)"
            ) from None
        # .save() appends the correct extension itself
        saved = obj.save(str(ctx.output_dir / "barcode"))
        if not saved:
            raise ToolError("barcode generation failed")
        ctx.progress(1.0, "done")
