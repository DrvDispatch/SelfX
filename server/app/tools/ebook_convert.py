"""ebook-convert: convert between ebook formats with Calibre's ebook-convert CLI."""

import os
import shutil
import zipfile

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

# Calibre --output-profile values worth exposing (subset of the full list). The
# empty string means "let Calibre pick its default", preserving current behavior.
_OUTPUT_PROFILES = ["", "default", "tablet", "kindle", "kindle_pw3", "kindle_oasis",
                    "kobo", "ipad3", "generic_eink", "generic_eink_hd"]


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
            },
            "output_profile": {
                "type": "string",
                "title": "Output device profile",
                "description": "Target device screen profile for correct sizing (blank = Calibre default).",
                "enum": _OUTPUT_PROFILES,
                "default": "",
            },
            "smarten_punctuation": {
                "type": "boolean",
                "title": "Smarten punctuation",
                "description": "Convert plain quotes/dashes/ellipses to their typographic equivalents.",
                "default": False,
            },
            "embed_all_fonts": {
                "type": "boolean",
                "title": "Embed all fonts",
                "description": "Embed every referenced font into the output (larger file, consistent look).",
                "default": False,
            },
            "enable_heuristics": {
                "type": "boolean",
                "title": "Enable heuristics",
                "description": "Fix chapter breaks, soft hyphens and wrapped lines (helps messy/OCR'd or PDF sources).",
                "default": False,
            },
            "title": {
                "type": "string",
                "title": "Title",
                "description": "Override the book title in the output metadata (blank = keep source).",
                "default": "",
            },
            "authors": {
                "type": "string",
                "title": "Author(s)",
                "description": "Override the author metadata; separate multiple with '&' (blank = keep source).",
                "default": "",
            },
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

        argv = ["ebook-convert", str(src), str(out)]
        argv += self._quality_args(ctx, src)

        # Isolate Calibre's config dir per job so parallel jobs don't contend on
        # the shared ~/.config/calibre lock / plugin cache under concurrency.
        cal_cfg = ctx.workdir / "calibre_config"
        env = {**os.environ, "CALIBRE_CONFIG_DIRECTORY": str(cal_cfg)}
        ctx.run_cmd(argv, timeout=600, env=env)
        self._validate_output(out, to)
        ctx.progress(1.0, "done")

    def _quality_args(self, ctx: ToolContext, src) -> list[str]:
        """Build the optional, opt-in Calibre flags. Defaults reproduce prior output."""
        p = ctx.params
        args: list[str] = []

        profile = str(p.get("output_profile", "") or "").strip()
        if profile and profile in _OUTPUT_PROFILES and profile != "":
            args += ["--output-profile", profile]

        if bool(p.get("smarten_punctuation", False)):
            args.append("--smarten-punctuation")
        if bool(p.get("embed_all_fonts", False)):
            args.append("--embed-all-fonts")
        if bool(p.get("enable_heuristics", False)):
            args.append("--enable-heuristics")
            # Calibre's PDF reader wraps lines hard; unwrap them when reflowing.
            if src.suffix.lower() == ".pdf":
                args.append("--unwrap-lines")

        title = str(p.get("title", "") or "").strip()
        if title:
            args += ["--title", title]
        authors = str(p.get("authors", "") or "").strip()
        if authors:
            args += ["--authors", authors]
        return args

    def _validate_output(self, out, to: str) -> None:
        """Structural, format-aware output validation (not just st_size > 0)."""
        if not out.is_file() or out.stat().st_size == 0:
            raise ToolError("conversion produced no output — the ebook may be DRM-protected or unsupported")
        if to == "pdf":
            validate_pdf_output(out, min_pages=1)
            return
        # EPUB and DOCX are ZIP containers; a truncated archive is a real failure.
        if to in ("epub", "docx") and not zipfile.is_zipfile(out):
            raise ToolError("conversion produced a corrupt (unreadable) output container")
