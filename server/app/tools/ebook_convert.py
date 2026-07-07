"""ebook-convert: convert between ebook formats with Calibre's ebook-convert CLI."""

import shutil

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class EbookConvert(Tool):
    slug = "ebook-convert"
    name = "Convert ebook"
    category = "documents"
    description = "Convert ebooks between EPUB, MOBI, AZW3, FB2, PDF, DOCX and TXT (Calibre)."
    accepts = [".epub", ".mobi", ".azw3", ".azw", ".fb2", ".lit", ".pdb",
               ".rtf", ".html", ".htm", ".docx", ".txt", ".pdf"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "title": "Convert to",
                "enum": ["epub", "mobi", "azw3", "fb2", "pdf", "docx", "txt"],
                "default": "epub",
            }
        },
        "required": ["to"],
    }

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("ebook-convert"):
            return True, None
        return False, "the ebook engine (Calibre) is not installed"

    def run(self, ctx: ToolContext) -> None:
        to = str(ctx.params.get("to", "epub"))
        src = ctx.input_paths[0]
        if src.suffix.lower().lstrip(".") == to:
            raise ToolError(f"the file is already in {to} format")
        out = ctx.output_dir / f"{src.stem}.{to}"
        ctx.progress(0.3, f"converting to {to}")
        ctx.run_cmd(["ebook-convert", str(src), str(out)], timeout=600)
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("conversion produced no output — the ebook may be DRM-protected")
        ctx.progress(1.0, "done")
