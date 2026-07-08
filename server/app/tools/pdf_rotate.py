"""pdf-rotate: rotate all pages of a PDF by a multiple of 90 degrees."""

import pikepdf

from .base import Tool, ToolContext, ToolError
from .pdf_split import _parse_pages
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
            },
            "pages": {
                "type": "string",
                "title": "Pages",
                "description": "Which pages to rotate, e.g. 1-3,7 (open-ended '5-' or '-3' also work) — leave empty to rotate every page.",
                "default": "",
                "maxLength": 200,
            },
            "which": {
                "type": "string",
                "title": "Restrict to",
                "description": "Further limit the selected pages to odd or even pages.",
                "enum": ["all", "odd", "even"],
                "default": "all",
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Password to open the input if it is encrypted — leave blank for unprotected PDFs.",
                "default": "",
                "maxLength": 128,
            },
            "linearize": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "description": "Linearize the rotated file for fast web view. Off keeps the classic layout.",
                "default": False,
            },
        },
        "required": ["angle"],
    }

    def run(self, ctx: ToolContext) -> None:
        angle = int(ctx.params.get("angle", 90))
        if angle not in (90, 180, 270):
            raise ToolError("rotation must be 90, 180 or 270 degrees")
        spec = str(ctx.params.get("pages", "")).strip()
        which = str(ctx.params.get("which", "all")).lower()
        if which not in ("all", "odd", "even"):
            which = "all"
        password = str(ctx.params.get("password", ""))
        linearize = bool(ctx.params.get("linearize", False))
        src = ctx.input_paths[0]
        try:
            pdf = pikepdf.open(src, password=password)
        except pikepdf.PasswordError:
            raise ToolError(
                "the PDF is password-protected — provide the password or unlock it first"
            ) from None
        except pikepdf.PdfError:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            total = len(pdf.pages)
            # Build the 0-based set of pages to rotate; default is every page.
            if spec:
                selected = set(_parse_pages(spec, total))
            else:
                selected = set(range(total))
            if which == "odd":  # 1-based odd pages -> even 0-based indices
                selected = {i for i in selected if i % 2 == 0}
            elif which == "even":  # 1-based even pages -> odd 0-based indices
                selected = {i for i in selected if i % 2 == 1}
            if not selected:
                raise ToolError("no pages matched the selection")
            for i, page in enumerate(pdf.pages):
                if i in selected:
                    page.rotate(angle, relative=True)
            ctx.progress(0.8, "saving")
            save_kwargs = {"linearize": True} if linearize else {}
            pdf.save(ctx.output_dir / f"{src.stem}-rotated.pdf", **save_kwargs)
        finally:
            pdf.close()
        ctx.progress(1.0, "done")
