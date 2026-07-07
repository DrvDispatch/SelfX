"""pdf-to-docx: convert a PDF to an editable Word document with pdf2docx (SPEC §8).

Best for digital/text PDFs; scanned/image PDFs need OCR first (no text layer to
reconstruct). pdf2docx is MIT but pulls in AGPL PyMuPDF (REPORT §2.1).
"""

from .base import Tool, ToolContext, ToolError
from .registry import register


@register
class PdfToDocx(Tool):
    slug = "pdf-to-docx"
    name = "PDF to Word"
    category = "pdf"
    description = "Convert a PDF into an editable Word (.docx) document, reconstructing layout."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext) -> None:
        # imported lazily so a heavy/optional dependency can't break tool discovery
        try:
            from pdf2docx import Converter
        except Exception:
            raise ToolError("the PDF-to-Word engine is not available on this server") from None

        src = ctx.input_paths[0]
        out_path = ctx.output_dir / f"{src.stem}.docx"
        ctx.progress(0.2, "converting PDF to Word")
        cv = None
        try:
            cv = Converter(str(src))
            cv.convert(str(out_path))
        except Exception:
            raise ToolError(
                "could not convert this PDF — it may be scanned (image-only), "
                "encrypted, or have a layout the converter can't reconstruct"
            ) from None
        finally:
            if cv is not None:
                try:
                    cv.close()
                except Exception:
                    pass
        if not out_path.is_file():
            raise ToolError("conversion produced no output")
        ctx.progress(1.0, "saved .docx")
