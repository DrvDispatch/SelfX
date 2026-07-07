"""pdf-compress: shrink a PDF with Ghostscript's pdfwrite device (SPEC §8).

Ghostscript is AGPL-flagged (REPORT §2.1) and reached only through this one adapter
with fixed argv flags — no user string ever becomes a gs option.
"""

import shutil

from .base import Tool, ToolContext, ToolError
from .registry import register

_QUALITY = {
    "screen": "/screen",  # 72 dpi, smallest
    "ebook": "/ebook",  # 150 dpi, good balance (default)
    "printer": "/printer",  # 300 dpi, larger
}


@register
class PdfCompress(Tool):
    slug = "pdf-compress"
    name = "Compress PDF"
    category = "pdf"
    description = "Reduce PDF file size by downsampling and re-encoding images (Ghostscript)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "quality": {
                "type": "string",
                "title": "Quality",
                "description": "screen = smallest, printer = highest quality",
                "enum": ["screen", "ebook", "printer"],
                "default": "ebook",
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        quality = str(ctx.params.get("quality", "ebook"))
        setting = _QUALITY.get(quality)
        if setting is None:
            raise ToolError(f"unknown quality '{quality}'")
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}-compressed.pdf"
        ctx.progress(0.2, f"compressing ({quality})")
        ctx.run_cmd(
            [
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.6",
                f"-dPDFSETTINGS={setting}",
                # De-duplicate repeated images and subset/compress fonts so the
                # re-encode actually shrinks image- and font-heavy documents.
                "-dDetectDuplicateImages=true",
                "-dCompressFonts=true",
                "-dSubsetFonts=true",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                "-dSAFER",
                f"-sOutputFile={out_path}",
                str(src),
            ]
        )
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise ToolError("compression produced no output — the PDF may be corrupt")
        # Never hand back a file bigger than the input: Ghostscript's re-encode can
        # inflate already-optimized, vector-heavy, or text-only PDFs. If there's no
        # gain, replace the output with the original bytes and report no reduction.
        src_size = src.stat().st_size
        out_size = out_path.stat().st_size
        if out_size >= src_size:
            shutil.copyfile(src, out_path)
            ctx.progress(1.0, f"already optimal — kept original ({src_size:,} bytes, no gain)")
        else:
            saved = 100.0 * (1.0 - out_size / src_size) if src_size else 0.0
            ctx.progress(1.0, f"compressed {src_size:,} → {out_size:,} bytes ({saved:.0f}% smaller)")
