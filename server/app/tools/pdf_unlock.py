"""pdf-unlock: remove the password from a PDF you can already open."""

import pikepdf

from ._docutil import validate_pdf_output
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
            },
            "strip_metadata": {
                "type": "boolean",
                "title": "Remove metadata",
                "description": "Scrub document info / XMP for privacy.",
                "default": False,
            },
            "linearize": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "default": False,
            },
        },
        "required": ["password"],
    }

    def run(self, ctx: ToolContext) -> None:
        password = str(ctx.params["password"])
        strip_metadata = bool(ctx.params.get("strip_metadata", False))
        linearize = bool(ctx.params.get("linearize", False))
        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}-unlocked.pdf"

        # Probe without a password first so we can tell "not encrypted" and
        # "owner-only restrictions" apart from "wrong password", instead of the
        # old conflated message.
        pdf = None
        note = "removing password"
        try:
            try:
                pdf = pikepdf.open(str(src))
                # Opened with no password → no user (open) password; the file was
                # either unencrypted or only had permission (owner) restrictions.
                note = "no open password — removing any restrictions"
            except pikepdf.PasswordError:
                try:
                    pdf = pikepdf.open(str(src), password=password)
                except pikepdf.PasswordError:
                    raise ToolError("wrong password for this PDF") from None
            except pikepdf.PdfError:
                raise ToolError("the input is not a valid PDF file") from None

            ctx.progress(0.6, note)
            if strip_metadata:
                try:
                    del pdf.Root.Metadata
                except Exception:
                    pass
                try:
                    pdf.docinfo = pikepdf.Dictionary()
                except Exception:
                    pass
            save_kw = {}
            if linearize:
                save_kw["linearize"] = True
            pdf.save(out, **save_kw)  # no encryption = removed
        finally:
            if pdf is not None:
                pdf.close()
        validate_pdf_output(out, min_pages=1)
        ctx.progress(1.0, "done")
