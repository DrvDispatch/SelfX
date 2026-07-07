"""pdf-unlock: remove the password from a PDF you can already open."""

import pikepdf

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfUnlock(Tool):
    slug = "pdf-unlock"
    name = "Unlock PDF"
    category = "pdf"
    description = "Remove the password from a PDF (you must supply the current password)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "title": "Current password",
                "minLength": 1,
                "maxLength": 128,
            }
        },
        "required": ["password"],
    }

    def run(self, ctx: ToolContext) -> None:
        password = str(ctx.params["password"])
        src = ctx.input_paths[0]
        try:
            pdf = pikepdf.open(src, password=password)
        except pikepdf.PasswordError:
            raise ToolError("wrong password, or the PDF is not password-protected") from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            ctx.progress(0.6, "removing password")
            pdf.save(ctx.output_dir / f"{src.stem}-unlocked.pdf")  # no encryption = removed
        finally:
            pdf.close()
        ctx.progress(1.0, "done")
