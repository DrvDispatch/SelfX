"""pdf-compress: shrink a PDF with Ghostscript's pdfwrite device (SPEC §8).

Ghostscript is AGPL-flagged (REPORT §2.1) and reached only through this one adapter.
Every gs option name is fixed in code; the only user-derived values are validated/
clamped scalars (an integer DPI and an optional password) passed as the VALUE half of a
single atomic argv element under shell=False, so no user string can inject a new gs flag.
"""

import shutil

import pikepdf

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
            },
            "image_dpi": {
                "type": "integer",
                "title": "Image resolution (DPI)",
                "description": "Override the preset image resolution. 0 = use the quality preset's default.",
                "default": 0,
                "minimum": 0,
                "maximum": 1200,
            },
            "fast_web_view": {
                "type": "boolean",
                "title": "Optimize for web (linearize)",
                "description": "Linearize the output so it streams a page at a time in browsers.",
                "default": False,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Password to open the input if it is encrypted — leave blank for unprotected PDFs.",
                "default": "",
                "maxLength": 128,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        quality = str(ctx.params.get("quality", "ebook"))
        setting = _QUALITY.get(quality)
        if setting is None:
            raise ToolError(f"unknown quality '{quality}'")
        try:
            image_dpi = int(ctx.params.get("image_dpi", 0) or 0)
        except (TypeError, ValueError):
            image_dpi = 0
        # Clamp to a sane band; 0 means "leave the preset alone".
        if image_dpi and not (9 <= image_dpi <= 1200):
            image_dpi = max(9, min(1200, image_dpi))
        fast_web_view = bool(ctx.params.get("fast_web_view", False))
        password = str(ctx.params.get("password", ""))

        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}-compressed.pdf"
        ctx.progress(0.2, f"compressing ({quality})")

        argv = [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.6",
            f"-dPDFSETTINGS={setting}",
            # De-duplicate repeated images and subset/compress fonts so the
            # re-encode actually shrinks image- and font-heavy documents.
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
        ]
        if image_dpi:
            # Explicit resolution overrides the preset's bundled DPI. Later flags win
            # over -dPDFSETTINGS, so these take effect.
            argv += [
                "-dDownsampleColorImages=true",
                "-dColorImageDownsampleType=/Bicubic",
                f"-dColorImageResolution={image_dpi}",
                "-dDownsampleGrayImages=true",
                "-dGrayImageDownsampleType=/Bicubic",
                f"-dGrayImageResolution={image_dpi}",
                "-dDownsampleMonoImages=true",
                "-dMonoImageDownsampleType=/Subsample",
                f"-dMonoImageResolution={image_dpi}",
            ]
        if fast_web_view:
            argv.append("-dFastWebView=true")
        if password:
            # VALUE-half of a single fixed-name option; atomic argv element under
            # shell=False, so it cannot inject an additional gs flag.
            argv.append(f"-sPDFPassword={password}")
        argv += [
            "-dNOPAUSE",
            "-dBATCH",
            "-dQUIET",
            "-dSAFER",
            f"-sOutputFile={out_path}",
            str(src),
        ]
        ctx.run_cmd(argv)

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
            return
        # We are keeping the gs output — guard against a truncated run that leaves a
        # non-empty but page-short file (a >0-byte output can still be missing pages).
        # Compare page counts when both documents can be opened; skip silently if either
        # cannot (e.g. unknown password) rather than raise a false alarm.
        try:
            with pikepdf.open(src, password=password) as _s, pikepdf.open(out_path) as _o:
                src_pages, out_pages = len(_s.pages), len(_o.pages)
        except Exception:
            src_pages = out_pages = None
        if src_pages is not None and out_pages is not None and out_pages != src_pages:
            raise ToolError(
                f"compression produced a broken PDF ({out_pages} of {src_pages} pages) — "
                "the input may be damaged"
            )
        saved = 100.0 * (1.0 - out_size / src_size) if src_size else 0.0
        ctx.progress(1.0, f"compressed {src_size:,} → {out_size:,} bytes ({saved:.0f}% smaller)")
