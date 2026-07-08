"""pdf-merge: combine multiple PDFs into one with pikepdf (SPEC §8)."""

from pathlib import Path

import pikepdf

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfMerge(Tool):
    slug = "pdf-merge"
    name = "Merge PDFs"
    category = "pdf"
    description = "Combine multiple PDF files into a single document, in upload order."
    accepts = [".pdf"]
    multi_file = True
    min_files = 2
    params_schema = {
        "type": "object",
        "properties": {
            "output_name": {
                "type": "string",
                "title": "Output file name",
                "description": "Name for the merged file (extension optional) — leave blank for 'merged.pdf'.",
                "default": "",
                "maxLength": 100,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Password to open the inputs if they are encrypted — leave blank for unprotected PDFs.",
                "default": "",
                "maxLength": 128,
            },
            "linearize": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "description": "Linearize the merged file for fast web view. Off keeps the classic layout.",
                "default": False,
            },
        },
    }
    queue = "default"

    @staticmethod
    def _output_name(raw: str) -> str:
        """Derive a safe output filename from a user string; default 'merged.pdf'."""
        raw = str(raw or "").strip()
        if not raw:
            return "merged.pdf"
        # Path(...).stem drops any directory and extension, then keep only safe chars.
        stem = Path(raw).stem
        stem = "".join(ch for ch in stem if ch.isalnum() or ch in (" ", "-", "_")).strip()
        return f"{stem}.pdf" if stem else "merged.pdf"

    def run(self, ctx: ToolContext) -> None:
        password = str(ctx.params.get("password", ""))
        linearize = bool(ctx.params.get("linearize", False))
        out_name = self._output_name(ctx.params.get("output_name", ""))

        merged = pikepdf.new()
        # Keep every source handle open until AFTER merged.save(): pikepdf copies
        # indirect/shared resources (fonts, XObjects) lazily, so closing a source
        # before save can drop objects and corrupt the merged file.
        sources: list = []
        total = len(ctx.input_paths)
        try:
            for index, path in enumerate(ctx.input_paths):
                ctx.progress(index / total, f"merging PDF {index + 1} of {total}")
                try:
                    src = pikepdf.open(path, password=password)
                except pikepdf.PasswordError:
                    raise ToolError(
                        f"input PDF #{index + 1} is password-protected — "
                        "provide the password or remove it first"
                    ) from None
                except pikepdf.PdfError:
                    raise ToolError(f"input PDF #{index + 1} is not a valid PDF file") from None
                sources.append(src)
                merged.pages.extend(src.pages)
            if len(merged.pages) == 0:
                raise ToolError("the merged document would have no pages")
            ctx.progress(0.95, f"writing {out_name}")
            save_kwargs = {"linearize": True} if linearize else {}
            merged.save(ctx.output_dir / out_name, **save_kwargs)
        finally:
            for src in sources:
                try:
                    src.close()
                except Exception:
                    pass
            merged.close()
        ctx.progress(1.0, f"merged {total} PDFs")
