"""ocr-pdf: add a searchable text layer to a PDF with OCRmyPDF (SPEC §8).

OCRmyPDF wraps Tesseract + Ghostscript + qpdf; pure CPU. Language packs must be
installed in the deployment (the Docker image bundles eng/deu/fra/spa, but the
WSL-no-Docker deployment may only ship eng), so the chosen language is validated
against the packs actually installed before the job runs.
"""

import os
import re
import shutil
import subprocess

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

_LANGS = ["eng", "deu", "fra", "spa"]
_MODES = {"skip-text": "--skip-text", "redo-ocr": "--redo-ocr", "force-ocr": "--force-ocr"}
_LANG_RE = re.compile(r"[A-Za-z]{2,10}(?:_[A-Za-z0-9]{2,10})?$")


def _installed_langs() -> set[str]:
    """Tesseract language packs actually installed, or empty set if unknown."""
    exe = shutil.which("tesseract")
    if not exe:
        return set()
    try:
        proc = subprocess.run(
            [exe, "--list-langs"], capture_output=True, text=True, timeout=15, check=False
        )
    except Exception:
        return set()
    langs: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        # The first line is a header ("List of available languages ..."); skip it.
        if not line or " " in line or ":" in line:
            continue
        langs.add(line)
    return langs


@register
class OcrPdf(Tool):
    slug = "ocr-pdf"
    name = "OCR (searchable PDF)"
    category = "documents"
    description = "Add an invisible, searchable text layer to a scanned PDF (does not alter the visible page)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "title": "Language",
                "enum": _LANGS,
                "default": "eng",
            },
            "extra_languages": {
                "type": "string",
                "title": "Additional languages",
                "description": "Extra Tesseract codes for mixed-language pages, e.g. 'deu+fra' "
                               "(must be installed on the server).",
                "maxLength": 100,
            },
            "mode": {
                "type": "string",
                "title": "Text handling",
                "description": "skip-text keeps existing text; redo-ocr replaces a bad text "
                               "layer; force-ocr rasterizes and OCRs every page.",
                "enum": ["skip-text", "redo-ocr", "force-ocr"],
                "default": "skip-text",
            },
            "output_type": {
                "type": "string",
                "title": "Output type",
                "description": "PDF/A (archival, default) or plain PDF (faster, smaller, keeps colours).",
                "enum": ["pdfa", "pdf"],
                "default": "pdfa",
            },
            "deskew": {
                "type": "boolean",
                "title": "Deskew",
                "description": "Straighten crooked scans before OCR",
                "default": False,
            },
            "rotate_pages": {
                "type": "boolean",
                "title": "Auto-rotate pages",
                "description": "Detect and fix sideways/upside-down pages.",
                "default": False,
            },
            "clean": {
                "type": "boolean",
                "title": "Clean before OCR",
                "description": "Denoise the scan (via unpaper) to improve recognition.",
                "default": False,
            },
            "optimize": {
                "type": "string",
                "title": "Optimize output size",
                "description": "0 = none … 3 = maximum (higher levels may need extra tools).",
                "enum": ["default", "0", "1", "2", "3"],
                "default": "default",
            },
            "oversample": {
                "type": "integer",
                "title": "Oversample DPI",
                "description": "Re-sample low-resolution scans to this DPI before OCR (e.g. 300).",
                "minimum": 72,
                "maximum": 1200,
            },
        },
    }

    def available(self) -> tuple[bool, str | None]:
        if not shutil.which("ocrmypdf"):
            return False, "the OCR engine (OCRmyPDF) is not installed"
        if not shutil.which("tesseract"):
            return False, "the OCR engine (Tesseract) is not installed"
        return True, None

    def run(self, ctx: ToolContext) -> None:
        language = str(ctx.params.get("language", "eng"))
        if language not in _LANGS:
            raise ToolError(f"unsupported language '{language}'")
        # Gate on the packs actually installed so a missing pack yields a clear
        # message instead of a raw tesseract stderr tail deep in the run.
        installed = _installed_langs()
        if installed and language not in installed:
            have = ", ".join(sorted(installed)) or "none"
            raise ToolError(
                f"the '{language}' OCR language pack is not installed on this server "
                f"(installed: {have})"
            )
        # Optional additional languages (validated against installed packs).
        langs = [language]
        extra = str(ctx.params.get("extra_languages") or "").strip()
        if extra:
            for tok in re.split(r"[+,\s]+", extra):
                tok = tok.strip()
                if not tok:
                    continue
                if not _LANG_RE.match(tok):
                    raise ToolError(f"invalid language code '{tok}'")
                if installed and tok not in installed:
                    have = ", ".join(sorted(installed)) or "none"
                    raise ToolError(
                        f"the '{tok}' OCR language pack is not installed on this server "
                        f"(installed: {have})"
                    )
                if tok not in langs:
                    langs.append(tok)
        lang_arg = "+".join(langs)

        mode = str(ctx.params.get("mode", "skip-text"))
        if mode not in _MODES:
            raise ToolError(f"unsupported mode '{mode}'")
        output_type = str(ctx.params.get("output_type", "pdfa"))
        if output_type not in ("pdfa", "pdf"):
            raise ToolError(f"unsupported output type '{output_type}'")
        deskew = bool(ctx.params.get("deskew", False))
        rotate_pages = bool(ctx.params.get("rotate_pages", False))
        clean = bool(ctx.params.get("clean", False))
        optimize = str(ctx.params.get("optimize", "default"))
        oversample = ctx.params.get("oversample")

        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}-ocr.pdf"

        argv = [
            "ocrmypdf",
            "--language", lang_arg,
            _MODES[mode],
            "--output-type", output_type,
            "--jobs", str(os.cpu_count() or 1),
            "--quiet",
        ]
        if deskew:
            argv.append("--deskew")
        if rotate_pages:
            argv.append("--rotate-pages")
        if clean:
            argv.append("--clean")
        if optimize != "default":
            argv += ["--optimize", optimize]
        if oversample:
            argv += ["--oversample", str(max(72, min(1200, int(oversample))))]
        argv += [str(src), str(out_path)]
        ctx.progress(0.2, "running OCR (this can take a while)")
        ctx.run_cmd(argv)
        # Validate SEMANTIC output: a real PDF with >= 1 page.
        validate_pdf_output(out_path, min_pages=1)
        ctx.progress(1.0, "done")
