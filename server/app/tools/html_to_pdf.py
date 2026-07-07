"""html-to-pdf: render an HTML file to PDF with WeasyPrint (no browser needed)."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class HtmlToPdf(Tool):
    slug = "html-to-pdf"
    name = "HTML to PDF"
    category = "documents"
    description = "Render a self-contained HTML file to a print-quality PDF (CSS paged media)."
    accepts = [".html", ".htm"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {"type": "object", "properties": {}}

    def available(self) -> tuple[bool, str | None]:
        try:
            import weasyprint  # noqa: F401
            return True, None
        except Exception:
            return False, "the HTML-to-PDF engine (WeasyPrint) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from weasyprint import HTML

        src = ctx.input_paths[0]
        out = ctx.output_dir / f"{src.stem}.pdf"
        ctx.progress(0.4, "rendering HTML to PDF")
        try:
            HTML(filename=str(src)).write_pdf(str(out))
        except Exception:
            raise ToolError("could not render this HTML (embedded remote resources are not fetched)") from None
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("rendering produced no output")
        ctx.progress(1.0, "done")
