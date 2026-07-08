"""pdf-to-markdown: convert a document to clean Markdown with Docling (layout-aware)."""

from .base import Tool, ToolContext, ToolError
from .registry import register

# Export format -> (DoclingDocument method name, output extension).
_EXPORTS = {
    "markdown": ("export_to_markdown", "md"),
    "html": ("export_to_html", "html"),
    "json": ("export_to_dict", "json"),
    "doctags": ("export_to_doctags", "doctags.txt"),
}


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
    params_schema = {
        "type": "object",
        "properties": {
            "output": {
                "type": "string",
                "title": "Output format",
                "description": "Markdown (default), HTML, JSON or DocTags. "
                               "JSON/DocTags preserve structure for downstream RAG chunking.",
                "enum": ["markdown", "html", "json", "doctags"],
                "default": "markdown",
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        try:
            import docling  # noqa: F401
            return True, None
        except Exception:
            return False, "the document-understanding engine (Docling) is not installed"

    def run(self, ctx: ToolContext) -> None:
        from docling.document_converter import DocumentConverter

        out_fmt = str(ctx.params.get("output", "markdown"))
        if out_fmt not in _EXPORTS:
            raise ToolError(f"unsupported output format '{out_fmt}'")
        method_name, ext = _EXPORTS[out_fmt]

        src = ctx.input_paths[0]
        ctx.progress(0.3, "analysing document (first run downloads models)")
        try:
            result = DocumentConverter().convert(str(src))
        except Exception:
            raise ToolError("could not convert this document") from None

        try:
            doc = result.document
            exporter = getattr(doc, method_name)
            if out_fmt == "json":
                import json
                content = json.dumps(exporter(), ensure_ascii=False, indent=2)
            else:
                content = exporter()
        except AttributeError:
            raise ToolError(
                f"the installed engine version does not support '{out_fmt}' export"
            ) from None
        except Exception:
            raise ToolError("could not export the converted document") from None

        if not content or not content.strip():
            raise ToolError("no content could be extracted")
        (ctx.output_dir / f"{src.stem}.{ext}").write_text(content, encoding="utf-8")
        ctx.progress(1.0, "done")
