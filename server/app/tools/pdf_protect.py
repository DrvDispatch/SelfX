"""pdf-protect: encrypt a PDF with a password (AES-256)."""

import pikepdf

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfProtect(Tool):
    slug = "pdf-protect"
    name = "Password-protect PDF"
    category = "pdf"
    description = "Encrypt a PDF with a password (AES-256). The password is required to open it."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Required to open the resulting PDF",
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
            pdf = pikepdf.open(src)
        except pikepdf.PasswordError:
            raise ToolError("the PDF is already password-protected") from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            ctx.progress(0.6, "encrypting")
            pdf.save(
                ctx.output_dir / f"{src.stem}-protected.pdf",
                encryption=pikepdf.Encryption(owner=password, user=password, R=6),
            )
        finally:
            pdf.close()
        ctx.progress(1.0, "done")
