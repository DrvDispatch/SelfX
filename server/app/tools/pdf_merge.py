"""pdf-merge: combine multiple PDFs into one with pikepdf (SPEC §8)."""

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
    params_schema = {"type": "object", "properties": {}}
    queue = "default"

    def run(self, ctx: ToolContext) -> None:
        merged = pikepdf.new()
        total = len(ctx.input_paths)
        try:
            for index, path in enumerate(ctx.input_paths):
                ctx.progress(index / total, f"merging PDF {index + 1} of {total}")
                try:
                    with pikepdf.open(path) as src:
                        merged.pages.extend(src.pages)
                except pikepdf.PasswordError:
                    raise ToolError(
                        f"input PDF #{index + 1} is password-protected — remove the password first"
                    ) from None
                except pikepdf.PdfError:
                    raise ToolError(f"input PDF #{index + 1} is not a valid PDF file") from None
            if len(merged.pages) == 0:
                raise ToolError("the merged document would have no pages")
            ctx.progress(0.95, "writing merged.pdf")
            merged.save(ctx.output_dir / "merged.pdf")
        finally:
            merged.close()
        ctx.progress(1.0, f"merged {total} PDFs")
