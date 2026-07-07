"""pdf-to-markdown: convert a document to clean Markdown with Docling (layout-aware)."""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfToMarkdown(Tool):
    slug = "pdf-to-markdown"
    name = "PDF to Markdown"
    category = "documents"
    description = "Convert a PDF, DOCX or PPTX into clean, structured Markdown (great for notes / RAG)."
    accepts = [".pdf", ".docx", ".pptx", ".html", ".htm"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {"type": "object", "properties": {}}

    def available(self) -> tuple[bool, str | None]:
        try:
            import docling  # noqa: F401
            return True, None
        except Exception:
            return False, "the document-understanding engine (Docling) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from docling.document_converter import DocumentConverter

        src = ctx.input_paths[0]
        ctx.progress(0.3, "analysing document (first run downloads models)")
        try:
            result = DocumentConverter().convert(str(src))
            markdown = result.document.export_to_markdown()
        except Exception:
            raise ToolError("could not convert this document to Markdown") from None
        if not markdown.strip():
            raise ToolError("no content could be extracted")
        (ctx.output_dir / f"{src.stem}.md").write_text(markdown, encoding="utf-8")
        ctx.progress(1.0, "done")
