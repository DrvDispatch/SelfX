"""pdf-extract-text: pull the text layer out of a PDF into a .txt file."""

from pypdf import PdfReader

from .base import Tool, ToolContext, ToolError
from .pdf_split import _parse_pages
from .registry import register


@register
class PdfExtractText(Tool):
    slug = "pdf-extract-text"
    name = "Extract text from PDF"
    category = "pdf"
    description = "Extract the text layer of a PDF to a plain-text file (scanned PDFs need OCR first)."
    accepts = [".pdf"]
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "engine": {
                "type": "string",
                "title": "Engine",
                "description": "pymupdf = faster, better reading order (default); "
                               "pypdf = pure-Python fallback.",
                "enum": ["pymupdf", "pypdf"],
                "default": "pymupdf",
            },
            "mode": {
                "type": "string",
                "title": "Extraction mode",
                "description": "plain = fast flowing text; layout = preserve columns/tables by keeping spacing.",
                "enum": ["plain", "layout"],
                "default": "plain",
            },
            "pages": {
                "type": "string",
                "title": "Pages",
                "description": "Which pages to extract, e.g. 1-3,7 (open-ended '5-' or '-3' also work) — leave empty for the whole document.",
                "default": "",
                "maxLength": 200,
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
        mode = str(ctx.params.get("mode", "plain")).lower()
        if mode not in ("plain", "layout"):
            mode = "plain"
        spec = str(ctx.params.get("pages", "")).strip()
        password = str(ctx.params.get("password", ""))
        engine = str(ctx.params.get("engine", "pymupdf")).lower()

        src = ctx.input_paths[0]
        try:
            import fitz  # PyMuPDF
            has_fitz = True
        except Exception:
            has_fitz = False

        if engine == "pymupdf" and has_fitz:
            parts = self._extract_fitz(ctx, src, password, spec, mode)
        else:
            parts = self._extract_pypdf(ctx, src, password, spec, mode)

        text = "\n\n".join(parts).strip()
        if not text:
            raise ToolError("no text found — this PDF may be scanned; run OCR first")
        (ctx.output_dir / f"{src.stem}.txt").write_text(text, encoding="utf-8")
        ctx.progress(1.0, "done")

    def _select(self, spec: str, n: int) -> list[int]:
        return _parse_pages(spec, n) if spec else list(range(n))

    def _extract_fitz(self, ctx, src, password, spec, mode) -> list[str]:
        import fitz
        try:
            doc = fitz.open(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file") from None
        try:
            if doc.needs_pass:
                if not password or not doc.authenticate(password):
                    raise ToolError(
                        "the PDF is password-protected — unlock it first, or provide the password"
                        if not password else "could not decrypt the PDF — the password is wrong"
                    )
            total = doc.page_count or 1
            indices = self._select(spec, doc.page_count)
            # sort=True reconstructs natural reading order (columns/tables) — the
            # PyMuPDF equivalent of pypdf's slower "layout" mode.
            sort = mode == "layout"
            parts = []
            for step, i in enumerate(indices):
                ctx.progress(step / total, f"reading page {i + 1}")
                try:
                    parts.append(doc[i].get_text("text", sort=sort) or "")
                except Exception:
                    parts.append("")
            return parts
        finally:
            doc.close()

    def _extract_pypdf(self, ctx, src, password, spec, mode) -> list[str]:
        try:
            reader = PdfReader(str(src))
        except Exception:
            raise ToolError("the input is not a valid PDF file") from None
        if reader.is_encrypted:
            if password:
                try:
                    decrypted = reader.decrypt(password)
                except Exception:
                    decrypted = 0
                if not decrypted:
                    raise ToolError("could not decrypt the PDF — the password is wrong")
            else:
                raise ToolError(
                    "the PDF is password-protected — unlock it first, or provide the password"
                )
        total = len(reader.pages) or 1
        indices = self._select(spec, len(reader.pages))
        extract_kwargs = {"extraction_mode": "layout"} if mode == "layout" else {}
        parts = []
        for step, i in enumerate(indices):
            ctx.progress(step / total, f"reading page {i + 1}")
            try:
                parts.append(reader.pages[i].extract_text(**extract_kwargs) or "")
            except Exception:
                parts.append("")
        return parts
