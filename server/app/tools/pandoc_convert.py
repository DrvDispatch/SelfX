"""pandoc-convert: convert between markup formats with Pandoc (SPEC §8).

Great for Markdown/HTML/DOCX/EPUB/LaTeX round-trips. Native PDF output needs a LaTeX
engine (not shipped), but Pandoc can drive WeasyPrint (already installed for html-to-pdf)
as a LaTeX-free `--pdf-engine`, so PDF is produced here when WeasyPrint is present.
"""

import shutil
import zipfile

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

# target key -> Pandoc writer name
_WRITER = {
    "docx": "docx",
    "html": "html",
    "md": "markdown",
    "epub": "epub",
    "odt": "odt",
    "pdf": "pdf",  # handled specially in run()
    "rst": "rst",
    "latex": "latex",
    "plain": "plain",
}

# target key -> output file extension (defaults to the key itself)
_OUTEXT = {"latex": "tex", "plain": "txt"}

# ZIP-container outputs whose integrity we can cheaply verify
_ZIP_OUTPUTS = {"docx", "epub", "odt"}


@register
class PandocConvert(Tool):
    slug = "pandoc-convert"
    name = "Markup convert"
    category = "documents"
    description = "Convert between Markdown, HTML, Word, ODT, EPUB, reST, LaTeX and PDF with Pandoc."
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
                "enum": ["docx", "html", "md", "epub", "odt", "pdf", "rst", "latex", "plain"],
                "default": "html",
            },
            "extract_media": {
                "type": "boolean",
                "title": "Extract embedded images",
                "description": "Write images embedded in the source (DOCX/EPUB) as files instead of dropping them.",
                "default": False,
            },
            "standalone": {
                "type": "boolean",
                "title": "Standalone document",
                "description": "Emit a complete document with header/footer (HTML is always standalone).",
                "default": False,
            },
            "toc": {
                "type": "boolean",
                "title": "Table of contents",
                "description": "Generate a table of contents (implies a standalone document).",
                "default": False,
            },
        },
        "required": ["to"],
    }

    def available(self) -> tuple[bool, str | None]:
        if shutil.which("pandoc"):
            return True, None
        return False, "the markup-conversion engine (Pandoc) is not installed"

    def run(self, ctx: ToolContext) -> None:
        to = str(ctx.params.get("to", "html"))
        writer = _WRITER.get(to)
        if writer is None:
            raise ToolError(f"unsupported target format '{to}'")

        src = ctx.input_paths[0]
        ext = _OUTEXT.get(to, to)
        out_path = ctx.output_dir / f"{src.stem}.{ext}"
        ctx.progress(0.3, f"converting to {to}")

        argv = ["pandoc", str(src), "-o", str(out_path)]

        if to == "pdf":
            # No LaTeX in this image; drive WeasyPrint as a LaTeX-free PDF engine.
            if not shutil.which("weasyprint"):
                raise ToolError(
                    "PDF output isn't available here — use the "
                    "'Office / HTML / Markdown to PDF' tool instead"
                )
            argv += ["--pdf-engine=weasyprint"]
        else:
            # Pin the writer explicitly (fixes the md->markdown extension/writer mismatch).
            argv += ["--to", writer]
            # A bare HTML fragment (no <head><meta charset>) mojibakes non-ASCII text;
            # --standalone emits a complete, correctly-encoded document.
            if to == "html":
                argv.append("--standalone")

        # Opt-in enhancements (defaults reproduce prior output).
        if bool(ctx.params.get("extract_media", False)):
            argv += ["--extract-media", str(ctx.output_dir / "media")]
        if bool(ctx.params.get("toc", False)):
            argv.append("--toc")
        want_standalone = bool(ctx.params.get("standalone", False)) or bool(ctx.params.get("toc", False))
        if want_standalone and to not in ("html", "pdf") and "--standalone" not in argv:
            argv.append("--standalone")

        ctx.run_cmd(argv)
        self._validate_output(out_path, to)
        ctx.progress(1.0, "done")

    def _validate_output(self, out_path, to: str) -> None:
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise ToolError("conversion produced no output")
        if to == "pdf":
            validate_pdf_output(out_path, min_pages=1)
        elif to in _ZIP_OUTPUTS and not zipfile.is_zipfile(out_path):
            raise ToolError("conversion produced a corrupt (unreadable) output container")
