"""ocr-pdf: add a searchable text layer to a PDF with OCRmyPDF (SPEC §8).

OCRmyPDF wraps Tesseract + Ghostscript + qpdf; pure CPU. Language packs must be
installed in the image (see Dockerfile: eng/deu/fra/spa bundled).
"""

from .base import Tool, ToolContext, ToolError
from .registry import register

_LANGS = ["eng", "deu", "fra", "spa"]


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

    def run(self, ctx: ToolContext) -> None:
        language = str(ctx.params.get("language", "eng"))
        if language not in _LANGS:
            raise ToolError(f"unsupported language '{language}'")
        deskew = bool(ctx.params.get("deskew", False))
        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}-ocr.pdf"

        argv = ["ocrmypdf", "--language", language, "--skip-text", "--quiet"]
        if deskew:
            argv.append("--deskew")
        argv += [str(src), str(out_path)]
        ctx.progress(0.2, "running OCR (this can take a while)")
        ctx.run_cmd(argv)
        if not out_path.is_file():
            raise ToolError("OCR produced no output")
        ctx.progress(1.0, "done")
