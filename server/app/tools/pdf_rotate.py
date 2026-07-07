"""pdf-rotate: rotate all pages of a PDF by a multiple of 90 degrees."""

import pikepdf

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfRotate(Tool):
    slug = "pdf-rotate"
    name = "Rotate PDF"
    category = "pdf"
    description = "Rotate every page of a PDF clockwise by 90, 180 or 270 degrees."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "angle": {
                "type": "integer",
                "title": "Rotation",
                "enum": [90, 180, 270],
                "default": 90,
            }
        },
        "required": ["angle"],
    }

    def run(self, ctx: ToolContext) -> None:
        angle = int(ctx.params.get("angle", 90))
        if angle not in (90, 180, 270):
            raise ToolError("rotation must be 90, 180 or 270 degrees")
        src = ctx.input_paths[0]
        try:
            pdf = pikepdf.open(src)
        except pikepdf.PasswordError:
            raise ToolError("the PDF is password-protected — unlock it first") from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            for page in pdf.pages:
                page.rotate(angle, relative=True)
            ctx.progress(0.8, "saving")
            pdf.save(ctx.output_dir / f"{src.stem}-rotated.pdf")
        finally:
            pdf.close()
        ctx.progress(1.0, "done")
