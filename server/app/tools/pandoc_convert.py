"""pandoc-convert: convert between markup formats with Pandoc (SPEC §8).

Great for Markdown/HTML/DOCX/EPUB/LaTeX round-trips. PDF output needs a LaTeX engine
which this image does not ship, so PDF is redirected to the office-convert tool.
"""

from .base import Tool, ToolContext, ToolError
from .registry import register

_EXT = {
    "docx": "docx",
    "html": "html",
    "md": "markdown",
    "epub": "epub",
    "odt": "odt",
    "pdf": "pdf",  # handled specially in run()
}


@register
class PandocConvert(Tool):
    slug = "pandoc-convert"
    name = "Markup convert"
    category = "documents"
    description = "Convert between Markdown, HTML, Word, ODT, EPUB and LaTeX with Pandoc."
    accepts = [".md", ".markdown", ".html", ".htm", ".docx", ".odt", ".epub", ".tex", ".rst"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "title": "Convert to",
                "enum": ["docx", "html", "md", "epub", "odt", "pdf"],
                "default": "html",
            }
        },
        "required": ["to"],
    }

    def run(self, ctx: ToolContext) -> None:
        to = str(ctx.params.get("to", "html"))
        writer = _EXT.get(to)
        if writer is None:
            raise ToolError(f"unsupported target format '{to}'")
        if to == "pdf":
            raise ToolError(
                "PDF output isn't available here — use the "
                "'Office / HTML / Markdown to PDF' tool instead"
            )
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}.{to}"
        ctx.progress(0.3, f"converting to {to}")
        ctx.run_cmd(["pandoc", str(src), "-o", str(out_path)])
        if not out_path.is_file():
            raise ToolError("conversion produced no output")
        ctx.progress(1.0, "done")
