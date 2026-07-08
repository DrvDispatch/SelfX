"""pdf-to-docx: convert a PDF to an editable Word document with pdf2docx (SPEC §8).

Best for digital/text PDFs; scanned/image PDFs need OCR first (no text layer to
reconstruct). pdf2docx is MIT but pulls in AGPL PyMuPDF (REPORT §2.1).
"""

import os
import zipfile

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
    params_schema = {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "title": "PDF password",
                "description": "Only needed if the PDF is password-protected (leave blank otherwise).",
                "maxLength": 128,
            },
            "start_page": {
                "type": "integer",
                "title": "First page",
                "description": "1-based first page to convert (blank = from the start).",
                "minimum": 1,
            },
            "end_page": {
                "type": "integer",
                "title": "Last page",
                "description": "1-based last page to convert (blank = to the end).",
                "minimum": 1,
            },
            "multiprocessing": {
                "type": "boolean",
                "title": "Use all CPU cores",
                "description": "Convert pages in parallel — faster on large PDFs.",
                "default": False,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        # imported lazily so a heavy/optional dependency can't break tool discovery
        try:
            from pdf2docx import Converter
        except Exception:
            raise ToolError("the PDF-to-Word engine is not available on this server") from None

        src = ctx.input_paths[0]
        password = str(ctx.params.get("password") or "")

        # Detect encryption up front (pikepdf is a group dependency) so a
        # password-protected input gets a clear message instead of the generic
        # "layout can't be reconstructed" error, and can be decrypted in-place
        # when the password is supplied.
        conv_src = src
        try:
            import pikepdf
        except Exception:
            pikepdf = None
        if pikepdf is not None:
            try:
                with pikepdf.open(str(src)):
                    pass
            except pikepdf.PasswordError:
                if not password:
                    raise ToolError(
                        "this PDF is password-protected — supply its password (or unlock it first)"
                    ) from None
                try:
                    dec = ctx.workdir / f"{src.stem}-decrypted.pdf"
                    with pikepdf.open(str(src), password=password) as p:
                        p.save(str(dec))
                    conv_src = dec
                except pikepdf.PasswordError:
                    raise ToolError("wrong password for this PDF") from None
                except Exception:
                    raise ToolError("could not open this password-protected PDF") from None
            except pikepdf.PdfError:
                raise ToolError("the input is not a valid PDF file") from None
            except Exception:
                # A probe failure must not block conversion — let the converter try.
                pass

        # Optional page range (exposed as friendly 1-based; pdf2docx uses a
        # 0-based, end-exclusive range internally).
        kwargs: dict = {}
        start_page = ctx.params.get("start_page")
        end_page = ctx.params.get("end_page")
        if start_page is not None:
            s = int(start_page)
            if s < 1:
                raise ToolError("first page must be 1 or greater")
            kwargs["start"] = s - 1
        if end_page is not None:
            e = int(end_page)
            if e < 1:
                raise ToolError("last page must be 1 or greater")
            kwargs["end"] = e
        if "start" in kwargs and "end" in kwargs and kwargs["end"] <= kwargs["start"]:
            raise ToolError("last page must be greater than or equal to first page")
        if bool(ctx.params.get("multiprocessing", False)):
            kwargs["multi_processing"] = True
            kwargs["cpu_count"] = os.cpu_count() or 1

        out_path = ctx.output_dir / f"{src.stem}.docx"
        ctx.progress(0.2, "converting PDF to Word")
        cv = None
        try:
            cv = Converter(str(conv_src))
            cv.convert(str(out_path), **kwargs)
        except Exception:
            raise ToolError(
                "could not convert this PDF — it may be scanned (image-only) "
                "or have a layout the converter can't reconstruct"
            ) from None
        finally:
            if cv is not None:
                try:
                    cv.close()
                except Exception:
                    pass
        if not out_path.is_file():
            raise ToolError("conversion produced no output")
        # Semantic check: a real .docx is a zip that carries word/document.xml.
        if not (zipfile.is_zipfile(out_path) and self._is_docx(out_path)):
            raise ToolError("conversion produced an invalid Word document")
        ctx.progress(1.0, "saved .docx")

    @staticmethod
    def _is_docx(path) -> bool:
        try:
            with zipfile.ZipFile(path) as zf:
                return "word/document.xml" in zf.namelist()
        except Exception:
            return False
