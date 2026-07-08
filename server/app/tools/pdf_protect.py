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
                "description": "Required to open the resulting PDF (the user password).",
                "minLength": 1,
                "maxLength": 128,
            },
            "owner_password": {
                "type": "string",
                "title": "Owner password",
                "description": "Optional separate password for changing permissions "
                               "(blank = same as the open password).",
                "maxLength": 128,
            },
            "encryption": {
                "type": "string",
                "title": "Encryption strength",
                "description": "AES-256 (modern, default) or AES-128 for older readers.",
                "enum": ["aes-256", "aes-128"],
                "default": "aes-256",
            },
            "allow_printing": {
                "type": "boolean",
                "title": "Allow printing",
                "default": True,
            },
            "allow_copy": {
                "type": "boolean",
                "title": "Allow copying text/images",
                "default": True,
            },
            "allow_modify": {
                "type": "boolean",
                "title": "Allow editing the content",
                "default": True,
            },
            "allow_annotate": {
                "type": "boolean",
                "title": "Allow comments/annotations",
                "default": True,
            },
            "linearize": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "description": "Slightly slower; enables fast streaming/partial load.",
                "default": False,
            },
        },
        "required": ["password"],
    }

    def run(self, ctx: ToolContext) -> None:
        password = str(ctx.params["password"])
        owner_password = str(ctx.params.get("owner_password") or "") or password
        r = 4 if str(ctx.params.get("encryption", "aes-256")) == "aes-128" else 6
        allow_printing = bool(ctx.params.get("allow_printing", True))
        allow_copy = bool(ctx.params.get("allow_copy", True))
        allow_modify = bool(ctx.params.get("allow_modify", True))
        allow_annotate = bool(ctx.params.get("allow_annotate", True))
        linearize = bool(ctx.params.get("linearize", False))
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-protected.pdf"
        try:
            pdf = pikepdf.open(src)
        except pikepdf.PasswordError:
            raise ToolError("the PDF is already password-protected") from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            ctx.progress(0.6, "encrypting")
            perms = pikepdf.Permissions(
                accessibility=True,
                extract=allow_copy,
                modify_annotation=allow_annotate,
                modify_assembly=allow_modify,
                modify_form=allow_modify,
                modify_other=allow_modify,
                print_lowres=allow_printing,
                print_highres=allow_printing,
            )
            save_kw = {
                "encryption": pikepdf.Encryption(
                    owner=owner_password, user=password, R=r, allow=perms
                )
            }
            if linearize:
                save_kw["linearize"] = True
            pdf.save(out, **save_kw)
        finally:
            pdf.close()
        # Confirm the file round-trips: re-open with the user password.
        try:
            with pikepdf.open(str(out), password=password) as check:
                if len(check.pages) < 1:
                    raise ToolError("encryption produced an empty PDF")
        except ToolError:
            raise
        except Exception:
            raise ToolError("failed to produce a valid encrypted PDF") from None
        ctx.progress(1.0, "done")
