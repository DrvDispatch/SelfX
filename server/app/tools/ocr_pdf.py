"""ocr-pdf: add a searchable text layer to a PDF with OCRmyPDF (SPEC §8).

OCRmyPDF wraps Tesseract + Ghostscript + qpdf; pure CPU. Language packs must be
installed in the deployment (the Docker image bundles eng/deu/fra/spa, but the
WSL-no-Docker deployment may only ship eng), so the chosen language is validated
against the packs actually installed before the job runs.
"""

import shutil
import subprocess

from ._docutil import validate_pdf_output
from .base import Tool, ToolContext, ToolError
from .registry import register

_LANGS = ["eng", "deu", "fra", "spa"]


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
            "deskew": {
                "type": "boolean",
                "title": "Deskew",
                "description": "Straighten crooked scans before OCR",
                "default": False,
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
        deskew = bool(ctx.params.get("deskew", False))
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}-ocr.pdf"

        argv = ["ocrmypdf", "--language", language, "--skip-text", "--quiet"]
        if deskew:
            argv.append("--deskew")
        argv += [str(src), str(out_path)]
        ctx.progress(0.2, "running OCR (this can take a while)")
        ctx.run_cmd(argv)
        # Validate SEMANTIC output: a real PDF with >= 1 page.
        validate_pdf_output(out_path, min_pages=1)
        ctx.progress(1.0, "done")
